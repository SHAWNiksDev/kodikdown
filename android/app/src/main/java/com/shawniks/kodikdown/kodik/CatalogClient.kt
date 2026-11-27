package com.shawniks.kodikdown.kodik

import android.net.Uri
import android.text.Html
import com.shawniks.kodikdown.data.ResolvedVideo
import com.shawniks.kodikdown.data.StreamVariant
import com.shawniks.kodikdown.net.readResponse
import java.io.IOException
import java.net.URI
import org.json.JSONArray
import org.json.JSONObject
import okhttp3.Request

data class CatalogEpisode(val number: String, val url: String)
data class CatalogChoice(val player: String, val voice: String, val episodes: List<CatalogEpisode>)
data class Catalog(
    val url: String,
    val title: String,
    val choices: List<CatalogChoice>,
    val description: String = "",
    val poster: String = "",
)

class CatalogClient(private val kodik: KodikClient) {
    private val http = KodikClient.defaultHttpClient()
    private val yummy = "https://api.yani.tv"
    private val libriaOrigin = "https://aniliberty.top"
    private val libria = "$libriaOrigin/api/v1"
    private val cvh = "https://plapi.cdnvideohub.com/api/v1/player/sv"

    private suspend fun text(url: String, referer: String? = null, ajax: Boolean = false): String = http.readResponse(
        Request.Builder().url(url).header("User-Agent", KodikClient.USER_AGENT).apply {
            if (referer != null) header("Referer", referer)
            if (ajax) header("X-Requested-With", "XMLHttpRequest")
        }.build()
    ) { response ->
        if (!response.isSuccessful) throw IOException("HTTP ${response.code}")
        response.body?.string().orEmpty()
    }

    private suspend fun json(url: String) = JSONObject(text(url))

    suspend fun poster(url: String): ByteArray? {
        if (!url.startsWith("https://")) return null
        return http.readResponse(Request.Builder().url(url).build()) { response ->
            if (!response.isSuccessful) return@readResponse null
            val source = response.body?.source() ?: return@readResponse null
            if (source.request(512_001)) return@readResponse null
            source.readByteArray()
        }
    }

    suspend fun lookup(raw: String): Catalog? {
        val url = Uri.parse(normalize(raw))
        val host = url.host.orEmpty().lowercase()
        val path = url.path.orEmpty().trimEnd('/')
        val slug = path.substringAfterLast('/')
        if (host in GO_HOSTS && path.matches(Regex("/anime/[\\p{L}\\p{N}_-]+-[0-9]+"))) {
            return goCatalog(url.toString(), slug.substringAfterLast('-'))
        }
        if (host.dubHost() && path.matches(Regex("/(?:[\\p{L}\\p{N}_-]+/)*[0-9]+-[\\p{L}\\p{N}_-]+\\.html"))) {
            return dubCatalog(url.toString())
        }
        if (host.removePrefix("www.") in LIBRIA_HOSTS) {
            return libriaSlug(path)?.let { libriaCatalog(url.toString(), it) }
        }
        if (!slug.matches(Regex("[\\p{L}\\p{N}_-]+"))) return null
        return if (host.yummyHost() && (path == "/catalog/item/$slug" || path == "/anime/$slug")) {
            yummyCatalog(url.toString(), slug)
        } else null
    }

    private suspend fun yummyCatalog(url: String, slug: String): Catalog {
        val info = json("$yummy/anime/${Uri.encode(slug)}").getJSONObject("response")
        val id = info.getLong("anime_id")
        val videos = json("$yummy/anime/$id/videos").getJSONArray("response")
        val choices = linkedMapOf<Pair<String, String>, LinkedHashMap<String, CatalogEpisode>>()
        for (entry in videos.objects()) {
            val meta = entry.optJSONObject("data") ?: continue
            val player = meta.optString("player").removePrefix("Плеер ").trim()
            val voice = meta.optString("dubbing").removePrefix("Озвучка ").trim()
            val number = entry.optString("number")
            val embed = entry.optString("iframe_url")
            if (embed.isBlank() || !number.matches(EPISODE_NUMBER)) continue
            val link = URI(normalize(url)).resolve(embed).toString()
            if (player !in setOf("Kodik", "CVH") || !link.startsWith("https://")) continue
            choices.getOrPut(player to voice) { linkedMapOf() }
                .putIfAbsent(number, CatalogEpisode(number, link))
        }
        val image = info.optJSONObject("poster")?.optString("medium").orEmpty()
        return Catalog(url, info.getString("title"), choices.map { (key, entries) ->
            CatalogChoice(key.first, key.second, entries.values.sortedBy { it.number.toBigDecimal() })
        }, info.optString("description"), if (image.startsWith("//")) "https:$image" else image)
    }

    private suspend fun libriaCatalog(url: String, slug: String): Catalog {
        val release = json("$libria/anime/releases/${Uri.encode(slug)}")
        val entries = release.getJSONArray("episodes").objects().mapNotNull { entry ->
            val number = entry.optString("ordinal")
            val id = entry.optString("id")
            if (!number.matches(EPISODE_NUMBER) || !id.matches(Regex("[0-9a-f-]{36}")) ||
                libriaVariants(entry).isEmpty()) null
            else CatalogEpisode(number, "$libria/anime/releases/episodes/$id")
        }.sortedBy { it.number.toBigDecimal() }
        val poster = release.optJSONObject("poster")?.optString("src").orEmpty()
        return Catalog(
            url, release.getJSONObject("name").optString("main", slug),
            listOf(CatalogChoice("AniLiberty", "AniLiberty", entries)),
            release.optString("description"), if (poster.startsWith("/")) "$libriaOrigin$poster" else poster,
        )
    }

    private suspend fun goPage(url: String): String =
        JSONObject(text(url, ajax = true)).getJSONObject("data").getString("content")

    private fun goEmbeds(document: String): Map<Pair<String, String>, String> =
        tags(document, "button").mapNotNull { fields ->
            val player = fields["data-provider-title"]?.trim() ?: return@mapNotNull null
            val dub = fields["data-translation-title"]?.removeSuffix(" (ошибка)")?.trim() ?: return@mapNotNull null
            val link = fields["data-player"] ?: return@mapNotNull null
            (player to dub) to link
        }.toMap()

    private suspend fun goCatalog(url: String, id: String): Catalog {
        val origin = "https://animego.me"
        val pageUrl = "$origin/player/$id"
        val initial = goPage(pageUrl)
        val episodes = linkedMapOf<String, String>()
        fun addEpisodes(document: String) {
            tags(document, "div").forEach { attrs ->
                val episode = attrs["data-episode"]?.takeIf { it.matches(ID) } ?: return@forEach
                val number = attrs["data-episode-number"]?.takeIf { it.matches(EPISODE_NUMBER) } ?: return@forEach
                episodes[number] = "$origin/player/videos/$episode"
            }
        }
        addEpisodes(initial)
        val pages = tags(initial, "div").firstNotNullOfOrNull { it["data-anime-player-episodes-pages-value"] }
        if (pages != null) {
            val indexes = JSONArray(pages).objects().map { it.optInt("page") }.filter { it in 1..100 }.distinct()
            for (page in indexes) addEpisodes(goPage("$pageUrl/episodes?page=$page"))
        }
        val choices = goEmbeds(initial).mapNotNull { (source, embed) ->
            val (player, voice) = source
            if (player.lowercase() !in setOf("kodik", "cvh", "aniboom")) return@mapNotNull null
            val key = Uri.Builder().appendQueryParameter("player", player).appendQueryParameter("voice", voice).build().encodedQuery
            CatalogChoice(player, voice, goEpisodes(pageUrl, embed, episodes, key.orEmpty()))
        }
        return fromPage(url, text(url), choices)
    }

    private suspend fun dubCatalog(url: String): Catalog {
        val page = text(url)
        val embed = tags(page, "iframe").mapNotNull { it["src"] }.map { URI(url).resolve(it).toString() }
            .firstOrNull { isDubPlayer(Uri.parse(it).host.orEmpty()) } ?: return fromPage(url, page, emptyList())
        val player = text(embed, referer = url)
        val manifest = dubManifest(player) ?: return fromPage(url, page, emptyList())
        val endpoint = Uri.parse(URI(embed).resolve(manifest).toString())
        if (!isDubPlayer(endpoint.host.orEmpty()) || endpoint.path?.endsWith("/vid.php") != true) {
            return fromPage(url, page, emptyList())
        }
        val paths = tags(player, "option").mapNotNull { it["value"] }
            .filter { it.matches(Regex("/s[0-9]+/[0-9a-f]{24,64}")) }.distinct()
            .ifEmpty { listOfNotNull(endpoint.getQueryParameter("v")) }
        val episodes = paths.mapIndexed { index, path ->
            val playlist = endpoint.buildUpon().clearQuery().appendQueryParameter("v", path)
                .fragment(embed).build().toString()
            CatalogEpisode((index + 1).toString(), playlist)
        }
        return fromPage(url, page, listOf(CatalogChoice("AniDUB", "AniDUB", episodes)))
    }

    private fun fromPage(url: String, page: String, choices: List<CatalogChoice>): Catalog {
        val meta = tags(page, "meta").mapNotNull {
            val name = it["property"] ?: it["name"] ?: return@mapNotNull null
            name to it["content"].orEmpty()
        }.toMap()
        val title = meta["og:title"] ?: Regex("<title>([^<]+)").find(page)?.groupValues?.get(1)?.let(::decode)
            ?: Uri.parse(url).lastPathSegment.orEmpty()
        val poster = meta["og:image"].orEmpty().takeIf { it.isNotBlank() }?.let { URI(url).resolve(it).toString() }.orEmpty()
        return Catalog(url, title, choices, meta["og:description"] ?: meta["description"].orEmpty(), poster)
    }

    suspend fun resolve(raw: String): ResolvedVideo {
        val url = Uri.parse(normalize(raw))
        val host = url.host.orEmpty().lowercase()
        val path = url.path.orEmpty()
        val id = path.substringAfterLast('/')
        val extension = id.substringAfterLast('.', "").lowercase()
        val wrappers = Regex("/cdn-iframe/([0-9]+)(?:/([0-9]+))?(?:/([0-9]+))?").matchEntire(path)
        return when {
            host in GO_HOSTS && path.matches(Regex("/player/videos/[0-9]+")) && url.fragment != null -> {
                val query = Uri.parse("https://animego.me/?${url.encodedFragment}")
                val key = query.getQueryParameter("player").orEmpty() to query.getQueryParameter("voice").orEmpty()
                val endpoint = url.buildUpon().fragment(null).build().toString()
                val embed = goEmbeds(goPage(endpoint))[key] ?: throw IOException("Player or voice-over is unavailable for this episode")
                val link = URI(endpoint).resolve(embed).toString()
                if (Uri.parse(link).host.orEmpty() in GO_HOSTS && Uri.parse(link).path?.startsWith("/player/videos/") == true) {
                    throw IOException("Invalid player link")
                }
                resolve(link)
            }
            isDubPlayer(host) && path.endsWith("/vid.php") -> {
                val referer = url.fragment?.takeIf { Uri.parse(it).host == host }
                val playlist = url.buildUpon().fragment(null).build().toString()
                requireVideo("AniDUB", listOf(StreamVariant(0, playlist, referer = referer)))
            }
            host in setOf("aniboom.one", "aniboom.tv") && path.startsWith("/embed/") -> {
                val page = text(url.toString(), "https://animego.org/")
                val data = tags(page, "video").firstNotNullOfOrNull { it["data-parameters"] }
                    ?.let(::JSONObject) ?: throw IOException("AniBoom video is unavailable")
                val hls = data.optString("hls").ifBlank { data.optString("fallbackHls") }
                val playlist = if (hls.startsWith("https://")) hls else JSONObject(hls).getString("src")
                requireVideo("AniBoom", listOf(StreamVariant(0, playlist, referer = "https://aniboom.one/")))
            }
            "$url".startsWith("$libria/anime/releases/episodes/") ->
                requireVideo("AniLiberty", libriaVariants(json("$url")))
            host == "plapi.cdnvideohub.com" && path == "/api/v1/player/sv/video/$id" && id.matches(ID) ->
                cvhVideo(id)
            host.yummyHost() && path.equals("/iframeCVH.html", true) ->
                cvhEpisode(url.getQueryParameter("anime_id").orEmpty(), url.getQueryParameter("episode")?.toIntOrNull() ?: 1,
                    url.getQueryParameter("season")?.toIntOrNull(), url.getQueryParameter("dubbing"), 745)
            wrappers != null && (host.endsWith(".cdnvideohub.com") || host in setOf("animego.me", "animego.org")) ->
                cvhEpisode(wrappers.groupValues[1], wrappers.groupValues[3].toIntOrNull() ?: 1,
                    wrappers.groupValues[2].toIntOrNull(), url.getQueryParameter("dubbing"))
            extension == "mp4" || extension == "m3u8" -> {
                val title = id.substringBeforeLast('.').ifBlank { "video" }
                val kind = if (extension == "mp4") "mp4" else "hls"
                requireVideo(title, listOf(StreamVariant(0, "$url", kind)))
            }
            else -> kodik.resolve(raw)
        }
    }

    private suspend fun cvhEpisode(titleId: String, number: Int, season: Int?, voice: String?, publisher: Int = 747): ResolvedVideo {
        if (!titleId.matches(ID)) throw IOException("Invalid CVH link")
        val entries = json("$cvh/playlist?pub=$publisher&aggr=mali&id=$titleId").getJSONArray("items").objects()
        val seasons = entries.map { it.optInt("season", 1) }.distinct()
        val selectedSeason = seasons.singleOrNull() ?: season ?: seasons.minOrNull()
        val studio = voice?.removePrefix("Озвучка ")?.let(::voiceKey).orEmpty()
        val item = entries.firstOrNull {
            it.optInt("season", 1) == selectedSeason && it.optInt("episode", 1) == number &&
                (studio.isEmpty() || voiceKey(it.optString("voiceStudio")) == studio)
        } ?: throw IOException("CVH: this episode and voice-over were not returned by the player")
        return cvhVideo(item.getString("vkId"))
    }

    private suspend fun cvhVideo(id: String): ResolvedVideo {
        if (!id.matches(ID)) throw IOException("Invalid CVH video ID")
        val sources = json("$cvh/video/$id").getJSONObject("sources")
        val variants = CVH_QUALITY.mapNotNull { (key, quality) ->
            sources.optString(key).takeIf { it.startsWith("https://") }?.let {
                StreamVariant(quality, it, "mp4")
            }
        }.distinctBy { it.quality }
        val hls = sources.optString("hlsUrl")
        return requireVideo("CVH $id", variants.ifEmpty {
            if (hls.startsWith("https://")) listOf(StreamVariant(0, hls)) else emptyList()
        })
    }

    private fun libriaVariants(entry: JSONObject) = listOf(1080, 720, 480).mapNotNull { quality ->
        entry.optString("hls_$quality").takeIf { it.startsWith("https://") }?.let {
            StreamVariant(quality, it, referer = "$libriaOrigin/")
        }
    }

    private fun requireVideo(title: String, variants: List<StreamVariant>): ResolvedVideo {
        if (variants.isEmpty()) throw IOException("No downloadable streams")
        return ResolvedVideo(title, variants)
    }

    private fun JSONArray.objects(): List<JSONObject> =
        (0 until length()).mapNotNull { optJSONObject(it) }

    companion object {
        private val EPISODE_NUMBER = Regex("[0-9]{1,6}(?:\\.[0-9]{1,4})?")
        private val ID = Regex("[0-9]{1,24}")
        private val LIBRIA_HOSTS = setOf("aniliberty.top", "anilibria.top", "anilibria.app")
        private val LIBRIA_RELEASE = Regex("/(?:anime/releases/(?:release/)?|release/)([\\p{L}\\p{N}_-]+)(?:\\.html)?")
        private val GO_HOSTS = setOf("animego.me", "animego.org", "www.animego.me", "www.animego.org")
        private val DUB_HOSTS = setOf("anidub.com", "anidub.life", "anidub.pro", "anidub.digital")
        private val YUMMY_HOSTS = setOf("yani.tv", "yummyani.me", "yummy-anime.ru")
        private val CVH_QUALITY = listOf(
            "mpegFullHdUrl" to 1080, "mpegHighUrl" to 720, "mpegMediumUrl" to 480,
            "mpegLowUrl" to 360, "mpegLowestUrl" to 240, "mpegMobileUrl" to 144, "mpegTinyUrl" to 144,
        )

        private fun String.yummyHost() = YUMMY_HOSTS.any { this == it || endsWith(".$it") }
        internal fun libriaSlug(path: String): String? = LIBRIA_RELEASE.matchEntire(path)?.groupValues?.get(1)
        internal fun goEpisodes(base: String, embed: String, episodes: Map<String, String>, selection: String): List<CatalogEpisode> {
            if (episodes.isEmpty()) return listOf(CatalogEpisode("1", URI(base).resolve(embed).toString()))
            return episodes.map { (number, link) -> CatalogEpisode(number, "$link#$selection") }
                .sortedBy { it.number.toBigDecimal() }
        }
        private fun String.dubHost() = DUB_HOSTS.any { this == it || endsWith(".$it") }
        private fun isDubPlayer(host: String) = host.matches(Regex("player[0-9]+\\.ladonyvesna2005\\.info"))
        private fun voiceKey(value: String) = value.lowercase().filter { it.isLetterOrDigit() }
        private fun decode(value: String) = Html.fromHtml(value, Html.FROM_HTML_MODE_COMPACT).toString()

        internal fun dubManifest(player: String): String? =
            tags(player, "video").firstOrNull { it["id"] == "hls-video" }
                ?.get("data-stream-src")?.takeIf(String::isNotBlank)
                ?: tags(player, "source").firstOrNull { it["id"] == "vsource" }?.get("src")

        private fun tags(document: String, tag: String): List<Map<String, String>> {
            val attr = Regex("""([a-zA-Z0-9-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
            return Regex("<$tag\\b[^>]*>", RegexOption.IGNORE_CASE).findAll(document).map { match ->
                attr.findAll(match.value).associate { it.groupValues[1] to decode(it.groupValues[2].ifEmpty { it.groupValues[3] }) }
            }.toList()
        }

        fun normalize(raw: String): String {
            val text = raw.trim()
            val stats = Regex("^United video id:[ \\t]*([0-9]{1,24})[ \\t]*\\r?$", RegexOption.MULTILINE)
                .find(text)?.groupValues?.get(1)
            if (stats != null && text.contains("URL: https://player.cdnvideohub.com/"))
                return "https://plapi.cdnvideohub.com/api/v1/player/sv/video/$stats"
            val embed = Regex("""<iframe\b[^>]*?\bsrc\s*=\s*["']([^"']+)""", RegexOption.IGNORE_CASE)
                .find(text)?.groupValues?.get(1)?.replace("&amp;", "&") ?: text
            return if (embed.startsWith("//")) "https:$embed" else embed
        }
    }
}
