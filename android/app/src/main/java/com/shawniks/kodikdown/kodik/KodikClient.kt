package com.shawniks.kodikdown.kodik

import com.shawniks.kodikdown.data.EmbedInfo
import com.shawniks.kodikdown.data.PlayerPage
import com.shawniks.kodikdown.data.PlayerPayload
import com.shawniks.kodikdown.data.ResolvedVideo
import com.shawniks.kodikdown.data.StreamVariant
import com.shawniks.kodikdown.data.Translation
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

class KodikClient(
    private val client: OkHttpClient = defaultHttpClient()
) {
    private val endpointCache = ConcurrentHashMap<String, String>()
    private var preferredHost: String? = null

    companion object {
        const val USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        private val RETRY_STATUSES = setOf(429, 500, 502, 503, 504)
        private const val PROXY_MARKER = "/s/m/"
        private const val POST_ATTEMPTS = 3

        fun defaultHttpClient(): OkHttpClient {
            val dispatcher = okhttp3.Dispatcher().apply {
                maxRequests = 256
                maxRequestsPerHost = 64
            }
            val pool = okhttp3.ConnectionPool(64, 5, TimeUnit.MINUTES)
            return OkHttpClient.Builder()
                .dispatcher(dispatcher)
                .connectionPool(pool)
                .connectTimeout(12, TimeUnit.SECONDS)
                .readTimeout(20, TimeUnit.SECONDS)
                .writeTimeout(15, TimeUnit.SECONDS)
                .retryOnConnectionFailure(true)
                .followRedirects(true)
                .followSslRedirects(true)
                .build()
        }
    }

    suspend fun resolve(rawUrl: String, translation: Translation? = null): ResolvedVideo = withContext(Dispatchers.IO) {
        val embed = KodikParser.extractEmbed(rawUrl)
        var lastError: Exception? = null

        val hosts = candidateHosts(embed.domain)
        for (host in hosts) {
            try {
                val resolved = resolveOn(host, embed, translation)
                preferredHost = host
                return@withContext resolved
            } catch (e: Exception) {
                lastError = e
                continue
            }
        }
        throw lastError ?: IOException("Could not reach any Kodik mirror")
    }

    private suspend fun resolveOn(host: String, embed: EmbedInfo, translation: Translation?): ResolvedVideo {
        val page = loadPage(host, embed)
        val payload = translation?.asPayload() ?: page.payload
        val data = fetchLinks(host, embed, page, payload)

        val variants = buildVariants(data)
        if (variants.isEmpty()) {
            throw IOException("The player returned no playable streams")
        }

        val warnings = mutableListOf<String>()
        if (variants.any { it.url.contains(PROXY_MARKER) }) {
            warnings.add("proxy")
        }

        val defaultQ = data.optInt("default", 0).takeIf { it > 0 }

        return ResolvedVideo(
            title = page.title ?: embed.fallbackTitle,
            variants = variants,
            translations = page.translations,
            translation = translation ?: page.currentTranslation,
            defaultQuality = defaultQ,
            warnings = warnings
        )
    }

    private suspend fun loadPage(host: String, embed: EmbedInfo): PlayerPage {
        val url = embed.urlOn(host)
        val text = getText(url, referer = "https://$host/")
        return KodikParser.parsePlayerPage(text, embed)
    }

    private suspend fun fetchLinks(
        host: String,
        embed: EmbedInfo,
        initialPage: PlayerPage,
        payload: PlayerPayload
    ): JSONObject {
        var page = initialPage
        var lastError = ""

        for (attempt in 0 until POST_ATTEMPTS) {
            val endpoint = endpointFor(host, page)
            val result = postLinks(host, embed, page, payload, endpoint)
            if (result.first != null) {
                return result.first!!
            }
            lastError = result.second
            if (attempt + 1 < POST_ATTEMPTS) {
                page = loadPage(host, embed)
                delay((400 * (attempt + 1)).toLong())
            }
        }

        // Fallback to GET
        val endpoint = endpointFor(host, page)
        val result = getLinks(host, endpoint, payload)
        if (result.first != null) {
            return result.first!!
        }

        throw IOException("Video-info request failed: ${result.second.ifEmpty { lastError }}")
    }

    private fun postLinks(
        host: String,
        embed: EmbedInfo,
        page: PlayerPage,
        payload: PlayerPayload,
        endpoint: String
    ): Pair<JSONObject?, String> {
        val url = "https://$host$endpoint"
        val form = page.signedForm(payload)
        val bodyBuilder = FormBody.Builder()
        for ((k, v) in form) {
            bodyBuilder.add(k, v)
        }

        val request = Request.Builder()
            .url(url)
            .post(bodyBuilder.build())
            .header("User-Agent", USER_AGENT)
            .header("Referer", embed.urlOn(host))
            .header("Origin", "https://$host")
            .header("X-Requested-With", "XMLHttpRequest")
            .header("Accept", "application/json, text/javascript, */*; q=0.01")
            .build()

        return try {
            client.newCall(request).execute().use { response ->
                parseReply(response, "POST")
            }
        } catch (e: Exception) {
            Pair(null, "POST $endpoint failed: ${e.message}")
        }
    }

    private fun getLinks(
        host: String,
        endpoint: String,
        payload: PlayerPayload
    ): Pair<JSONObject?, String> {
        val baseUrl = "https://$host$endpoint".toHttpUrlOrNull() ?: return Pair(null, "Invalid endpoint URL")
        val urlBuilder = baseUrl.newBuilder()
        for ((k, v) in payload.asForm()) {
            urlBuilder.addQueryParameter(k, v)
        }

        val request = Request.Builder()
            .url(urlBuilder.build())
            .header("User-Agent", USER_AGENT)
            .header("Referer", "https://$host/")
            .header("X-Requested-With", "XMLHttpRequest")
            .header("Accept", "application/json, text/javascript, */*; q=0.01")
            .build()

        return try {
            client.newCall(request).execute().use { response ->
                parseReply(response, "GET")
            }
        } catch (e: Exception) {
            Pair(null, "GET $endpoint failed: ${e.message}")
        }
    }

    private suspend fun endpointFor(host: String, page: PlayerPage): String {
        val cached = endpointCache[host]
        if (page.playerJsPath.isEmpty()) {
            if (cached != null) return cached
            throw IOException("Page does not link the player script")
        }

        val jsUrl = "https://$host/${page.playerJsPath}"
        val playerJs = getText(jsUrl, referer = "https://$host/")
        val endpoint = KodikParser.extractEndpoint(playerJs)
        endpointCache[host] = endpoint
        return endpoint
    }

    private suspend fun getText(url: String, referer: String? = null): String {
        var response = executeRequest(url, referer)
        if (RETRY_STATUSES.contains(response.first)) {
            delay(500)
            response = executeRequest(url, referer)
        }
        if (response.first >= 400 || response.second == null) {
            throw IOException("HTTP ${response.first} for $url")
        }
        return response.second!!
    }

    private fun executeRequest(url: String, referer: String?): Pair<Int, String?> {
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", USER_AGENT)
            .header("Referer", referer ?: url)
            .build()

        return try {
            client.newCall(request).execute().use { res ->
                Pair(res.code, res.body?.string())
            }
        } catch (e: Exception) {
            Pair(0, null)
        }
    }

    private fun parseReply(response: okhttp3.Response, method: String): Pair<JSONObject?, String> {
        if (!response.isSuccessful) {
            return Pair(null, "$method returned HTTP ${response.code}")
        }
        val text = response.body?.string().orEmpty()
        return try {
            val json = JSONObject(text)
            if (json.has("error") && !json.isNull("error")) {
                Pair(null, json.getString("error"))
            } else {
                Pair(json, "")
            }
        } catch (e: Exception) {
            Pair(null, "$method reply is not valid JSON")
        }
    }

    private fun candidateHosts(requested: String): List<String> {
        val hosts = mutableListOf<String>()
        preferredHost?.let { if (it.isNotEmpty()) hosts.add(it) }
        if (requested.isNotEmpty() && !hosts.contains(requested)) {
            hosts.add(requested)
        }
        for (h in KodikParser.DEFAULT_HOSTS) {
            if (!hosts.contains(h)) hosts.add(h)
        }
        return hosts
    }

    private fun buildVariants(data: JSONObject): List<StreamVariant> {
        val links = data.optJSONObject("links") ?: return emptyList()
        val variants = mutableListOf<StreamVariant>()

        val keys = links.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            val quality = key.toIntOrNull() ?: continue
            val entries = links.optJSONArray(key) ?: continue

            var bestVariant: StreamVariant? = null
            var bestRank = 4

            for (i in 0 until entries.length()) {
                val entry = entries.optJSONObject(i) ?: continue
                val src = entry.optString("src", "")
                if (src.isEmpty()) continue

                val decoded = KodikDecoder.decodeStreamUrl(src, KodikDecoder.KNOWN_SHIFT) ?: continue
                val type = entry.optString("type", "").lowercase()
                val rank = when {
                    type.contains("mpegurl") || type.contains("m3u8") -> 0
                    type.contains("dash") || type.contains("mpd") -> 1
                    type.contains("mp4") || type.contains("video") -> 2
                    else -> 3
                }
                if (rank >= bestRank) continue

                var url = KodikDecoder.normaliseUrl(decoded.first)

                // If the decoded stream URL carries a lower resolution filename (e.g. /480.mp4 under quality 720)
                // promote the path to match the requested quality
                val fileRes = Regex("""/(\d{3,4})\.mp4""").find(url)?.groupValues?.get(1)?.toIntOrNull()
                if (fileRes != null && quality > fileRes) {
                    url = url.replace(Regex("""/(\d{3,4})\.mp4"""), "/$quality.mp4")
                }

                val (kind, directMp4) = KodikDecoder.streamKind(url)
                val direct = directMp4?.let { KodikDecoder.normaliseUrl(it) }

                bestVariant = StreamVariant(
                    quality = quality,
                    url = url,
                    kind = kind,
                    directMp4 = direct
                )
                bestRank = rank
            }

            if (bestVariant != null) {
                variants.add(bestVariant)
            }
        }

        // Sort descending by quality and deduplicate
        variants.sortByDescending { it.quality }
        val unique = mutableListOf<StreamVariant>()
        val seen = mutableSetOf<Int>()
        for (v in variants) {
            if (!seen.contains(v.quality)) {
                seen.add(v.quality)
                unique.add(v)
            }
        }
        return unique
    }
}
