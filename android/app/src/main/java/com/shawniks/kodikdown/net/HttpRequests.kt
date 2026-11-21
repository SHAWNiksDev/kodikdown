package com.shawniks.kodikdown.net

import java.io.IOException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response

/** Keep cancellation connected to the socket until the response body has been consumed. */
suspend fun <T> OkHttpClient.readResponse(request: Request, read: (Response) -> T): T {
    val call = newCall(request)
    val finished = CompletableDeferred<Unit>()
    try {
        return suspendCancellableCoroutine { continuation ->
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    try {
                        if (continuation.isActive) continuation.resumeWithException(e)
                    } finally {
                        finished.complete(Unit)
                    }
                }

                override fun onResponse(call: Call, response: Response) {
                    try {
                        val result =
                            response.use {
                                if (!continuation.isActive) throw IOException("Request cancelled")
                                read(it)
                            }
                        if (continuation.isActive) {
                            continuation.resume(result)
                        }
                    } catch (e: Exception) {
                        if (continuation.isActive) {
                            continuation.resumeWithException(e)
                        }
                    } finally {
                        finished.complete(Unit)
                    }
                }
            })
        }
    } catch (e: CancellationException) {
        // The caller may delete a partial file as soon as this function returns.
        withContext(NonCancellable) { finished.await() }
        throw e
    }
}
