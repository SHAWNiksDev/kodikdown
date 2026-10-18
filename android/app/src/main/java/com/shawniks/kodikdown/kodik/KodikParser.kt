package com.shawniks.kodikdown.kodik

import android.util.Base64
import com.shawniks.kodikdown.data.EmbedInfo
import com.shawniks.kodikdown.data.PlayerPage
import com.shawniks.kodikdown.data.PlayerPayload
import com.shawniks.kodikdown.data.Translation
import org.json.JSONObject
import java.net.URI
import java.nio.charset.StandardCharsets
import java.util.regex.Pattern

object KodikParser {
    val DEFAULT_HOSTS = listOf(
        "kodikplayer.com",
        "kodik.info",
        "kodik.biz",
        "kodik.cc",
        "aniqit.com"
    )

    private val EMBED_RE = Pattern.compile(
        "/([a-z][a-z-]*)/(\\d+)/([0-9a-z]{16,})(?:/(\\d{3,4})p?)?",
        Pattern.CASE_INSENSITIVE
    )
    private val IFRAME_SRC_RE = Pattern.compile(
        """<iframe[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
        Pattern.CASE_INSENSITIVE
    )
    private val QUERY_TAIL_RE = Pattern.compile("""^\?([^"'\s>]*)""")

    private val URL_PARAMS_RE = Pattern.compile(
        """urlParams\s*=\s*(["'])(\{.*?\})\1""",
        Pattern.DOTALL
    )
    private val SIGNED_VAR_RE = Pattern.compile(
        """\b(?:var|let|const|window\.)\s*(domain|d_sign|pd|pd_sign|ref|ref_sign)\s*=\s*["']([^"']*)["']"""
    )
    private val VAR_TO_PARAM = mapOf(
        "domain" to "d",
        "d_sign" to "d_sign",
        "pd" to "pd",
        "pd_sign" to "pd_sign",
        "ref" to "ref",
        "ref_sign" to "ref_sign"
    )

    private val VINFO_RE = Pattern.compile("""(?:\.|\b)(type|hash|id)\s*[:=]\s*'([^']*)'\s*[,;]?""")
    private val VINFO_DOUBLE_RE = Pattern.compile("""(?:\.|\b)(type|hash|id)\s*[:=]\s*"([^"]*)"\s*[,;]?""")

    private val TRANSLATION_ID_RE = Pattern.compile("""\btranslationId\s*=\s*(\d+)""")
    private val TRANSLATION_TITLE_RE = Pattern.compile("""\btranslationTitle\s*=\s*["']([^"']*)["']""")

    private val PLAYER_JS_PATTERNS = listOf(
        Pattern.compile(
            """<script\s[^>]*?src=["'](?:https?://[^/"']+)?/(assets/js/app\.player_single[^"']+?\.js)["']""",
            Pattern.CASE_INSENSITIVE
        ),
        Pattern.compile(
            """["'](?:https?://[^/"']+)?/(assets/js/app\.player[^"']*?\.js)["']""",
            Pattern.CASE_INSENSITIVE
        ),
        Pattern.compile(
            """<script\s[^>]*?src=["'](?:https?://[^/"']+)?/(assets/js/[^"']*player[^"']*?\.js)["']""",
            Pattern.CASE_INSENSITIVE
        )
    )

    private val AJAX_ATOB_RE = Pattern.compile("""url\s*:\s*atob\(\s*["']([A-Za-z0-9+/=]{4,})["']""")
    private val ATOB_RE = Pattern.compile("""atob\(\s*["']([A-Za-z0-9+/=]{4,})["']""")
    private val KNOWN_ENDPOINT_RE = Pattern.compile("""["'](/(?:ftor|gvi|kor|vtt))["']""")

    private val TITLE_RE = Pattern.compile("""<title>(.*?)</title>""", Pattern.CASE_INSENSITIVE or Pattern.DOTALL)
    private val OG_TITLE_RE = Pattern.compile(
        """<meta\s[^>]*?(?:property=["']og:title["'][^>]*?content=["']([^"']+)["']|content=["']([^"']+)["'][^>]*?property=["']og:title["'])""",
        Pattern.CASE_INSENSITIVE
    )
    private val GENERIC_TITLE_RE = Pattern.compile("^(kodik|kodik\\s*player|player)$", Pattern.CASE_INSENSITIVE)

    private val OPTION_TAG_RE = Pattern.compile("""<option\b([^>]*)>""", Pattern.CASE_INSENSITIVE or Pattern.DOTALL)
    private val OPTION_ATTR_RE = Pattern.compile("""([a-z][a-z-]*)\s*=\s*["']([^"']*)["']""", Pattern.CASE_INSENSITIVE)

    fun extractEmbed(raw: String): EmbedInfo {
        var text = unescapeHtml(raw.trim())
        val iframeMatcher = IFRAME_SRC_RE.matcher(text)
        if (iframeMatcher.find()) {
            text = iframeMatcher.group(1)?.trim() ?: text
        }

        if (text.startsWith("//")) {
            text = "https:$text"
        }
        if (!text.startsWith("http")) {
            text = "https://${text.trimStart('/')}"
        }

        val matcher = EMBED_RE.matcher(text)
        if (!matcher.find()) {
            throw IllegalArgumentException("Not a kodik embed URL: $raw")
        }

        val mediaType = matcher.group(1)!!.lowercase()
        val videoId = matcher.group(2)!!
        val contentHash = matcher.group(3)!!.lowercase()
        val qualityStr = matcher.group(4)
        val quality = qualityStr?.toIntOrNull()

        val host = getHostOf(text)
        val tail = text.substring(matcher.end()).trimStart('/')
        val queryMatcher = QUERY_TAIL_RE.matcher(tail)
        val query = if (queryMatcher.find()) queryMatcher.group(1) ?: "" else ""

        return EmbedInfo(
            domain = host,
            mediaType = mediaType,
            videoId = videoId,
            contentHash = contentHash,
            quality = quality,
            query = query
        )
    }

    private fun getHostOf(url: String): String {
        return try {
            val formatted = if (url.contains("://")) url else "https://${url.trimStart('/')}"
            URI(formatted).host?.lowercase() ?: url.substringAfter("//").substringBefore('/').substringBefore('?').lowercase()
        } catch (_: Exception) {
            url.substringAfter("//").substringBefore('/').substringBefore('?').lowercase()
        }
    }

    fun extractPayload(pageHtml: String): PlayerPayload? {
        val fields = mutableMapOf<String, String>()
        for (pattern in listOf(VINFO_RE, VINFO_DOUBLE_RE)) {
            val matcher = pattern.matcher(pageHtml)
            while (matcher.find()) {
                val field = matcher.group(1) ?: continue
                val value = matcher.group(2)?.trim() ?: continue
                if (!fields.containsKey(field)) {
                    fields[field] = value
                }
            }
        }
        val type = fields["type"]
        val id = fields["id"]
        val hash = fields["hash"]
        return if (type != null && id != null && hash != null) {
            PlayerPayload(type, id, hash)
        } else null
    }

    fun extractUrlParams(pageHtml: String): Map<String, String> {
        val params = mutableMapOf<String, String>()
        val jsonMatcher = URL_PARAMS_RE.matcher(pageHtml)
        if (jsonMatcher.find()) {
            val jsonStr = jsonMatcher.group(2) ?: ""
            try {
                val json = JSONObject(jsonStr)
                val keys = json.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    val value = json.optString(key, "")
                    if (value.isNotEmpty()) {
                        params[key] = value
                    }
                }
                if (params.isNotEmpty()) return params
            } catch (_: Exception) {}
        }

        val varMatcher = SIGNED_VAR_RE.matcher(pageHtml)
        while (varMatcher.find()) {
            val varName = varMatcher.group(1) ?: continue
            val varVal = varMatcher.group(2) ?: continue
            val paramName = VAR_TO_PARAM[varName] ?: varName
            if (!params.containsKey(paramName)) {
                params[paramName] = varVal
            }
        }
        return params
    }

    fun extractTranslations(pageHtml: String): List<Translation> {
        val translations = mutableListOf<Translation>()
        val seen = mutableSetOf<String>()
        val optionMatcher = OPTION_TAG_RE.matcher(pageHtml)
        while (optionMatcher.find()) {
            val attrsText = optionMatcher.group(1) ?: ""
            val attrs = mutableMapOf<String, String>()
            val attrMatcher = OPTION_ATTR_RE.matcher(attrsText)
            while (attrMatcher.find()) {
                val k = attrMatcher.group(1)!!.lowercase()
                val v = unescapeHtml(attrMatcher.group(2)!!.trim())
                attrs[k] = v
            }

            val mediaType = attrs["data-media-type"] ?: ""
            val mediaId = attrs["data-media-id"] ?: ""
            val contentHash = attrs["data-media-hash"]?.lowercase() ?: ""
            if (mediaType.isEmpty() || mediaId.isEmpty() || contentHash.isEmpty()) continue

            val identity = "$mediaType:$mediaId:$contentHash"
            if (seen.contains(identity)) continue
            seen.add(identity)

            translations.add(
                Translation(
                    title = attrs["data-title"] ?: mediaId,
                    mediaType = mediaType,
                    mediaId = mediaId,
                    contentHash = contentHash,
                    translationId = attrs["data-id"] ?: "",
                    kind = attrs["data-translation-type"] ?: "voice",
                    selected = attrsText.lowercase().contains("selected")
                )
            )
        }
        return translations
    }

    fun extractCurrentTranslation(
        pageHtml: String,
        translations: List<Translation>,
        payload: PlayerPayload?
    ): Translation? {
        if (translations.isEmpty()) return null

        for (t in translations) {
            if (t.selected) return t
        }

        val idMatcher = TRANSLATION_ID_RE.matcher(pageHtml)
        if (idMatcher.find()) {
            val wanted = idMatcher.group(1)
            for (t in translations) {
                if (t.translationId == wanted) return t
            }
        }

        val titleMatcher = TRANSLATION_TITLE_RE.matcher(pageHtml)
        if (titleMatcher.find()) {
            val wanted = unescapeHtml(titleMatcher.group(1)!!.trim()).lowercase()
            for (t in translations) {
                if (t.title.trim().lowercase() == wanted) return t
            }
        }

        if (payload != null) {
            for (t in translations) {
                if (t.mediaId == payload.videoId && t.contentHash == payload.contentHash) {
                    return t
                }
            }
        }
        return translations.firstOrNull()
    }

    fun findPlayerJsPath(pageHtml: String): String? {
        for (pattern in PLAYER_JS_PATTERNS) {
            val matcher = pattern.matcher(pageHtml)
            if (matcher.find()) {
                return matcher.group(1)
            }
        }
        return null
    }

    fun extractEndpoint(playerJs: String): String {
        val ajaxMatcher = AJAX_ATOB_RE.matcher(playerJs)
        if (ajaxMatcher.find()) {
            val decoded = decodeEndpoint(ajaxMatcher.group(1)!!)
            if (decoded != null) return decoded
        }

        val found = mutableListOf<String>()
        val atobMatcher = ATOB_RE.matcher(playerJs)
        while (atobMatcher.find()) {
            val decoded = decodeEndpoint(atobMatcher.group(1)!!)
            if (decoded != null) found.add(decoded)
        }

        for (ep in found) {
            if (!ep.contains(".") && ep.length <= 16) return ep
        }
        if (found.isNotEmpty()) return found.first()

        val knownMatcher = KNOWN_ENDPOINT_RE.matcher(playerJs)
        if (knownMatcher.find()) {
            return knownMatcher.group(1)!!
        }
        throw IllegalStateException("Video-info endpoint not found in player bundle")
    }

    private fun decodeEndpoint(encoded: String): String? {
        return try {
            val remainder = encoded.length % 4
            val padded = if (remainder > 0) encoded + "=".repeat(4 - remainder) else encoded
            val decoded = String(Base64.decode(padded, Base64.DEFAULT), StandardCharsets.UTF_8)
            if (decoded.startsWith("/") && decoded.length < 64 && !decoded.contains(" ")) {
                decoded
            } else null
        } catch (_: Exception) {
            null
        }
    }

    fun extractTitle(pageHtml: String): String? {
        var title = ""
        val titleMatcher = TITLE_RE.matcher(pageHtml)
        if (titleMatcher.find()) {
            title = titleMatcher.group(1) ?: ""
        }
        if (title.isEmpty()) {
            val ogMatcher = OG_TITLE_RE.matcher(pageHtml)
            if (ogMatcher.find()) {
                title = ogMatcher.group(1) ?: ogMatcher.group(2) ?: ""
            }
        }
        title = unescapeHtml(title).replace(Regex("\\s+"), " ").trim()
        if (title.isEmpty() || GENERIC_TITLE_RE.matcher(title).matches()) {
            return null
        }
        return title
    }

    fun parsePlayerPage(pageHtml: String, embed: EmbedInfo): PlayerPage {
        val payload = extractPayload(pageHtml)
        val urlParams = extractUrlParams(pageHtml)
        if (payload == null && urlParams.isEmpty()) {
            throw IllegalStateException("Page carries no Kodik player data")
        }

        val resolvedPayload = payload ?: PlayerPayload(embed.mediaType, embed.videoId, embed.contentHash)
        val translations = extractTranslations(pageHtml)
        return PlayerPage(
            payload = resolvedPayload,
            playerJsPath = findPlayerJsPath(pageHtml).orEmpty(),
            title = extractTitle(pageHtml),
            urlParams = urlParams,
            translations = translations,
            currentTranslation = extractCurrentTranslation(pageHtml, translations, resolvedPayload)
        )
    }

    private fun unescapeHtml(text: String): String {
        return text
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", "\"")
            .replace("&#39;", "'")
            .replace("&apos;", "'")
            .replace("&#x27;", "'")
    }
}
