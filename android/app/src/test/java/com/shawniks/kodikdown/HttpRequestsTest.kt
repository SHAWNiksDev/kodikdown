package com.shawniks.kodikdown

import com.shawniks.kodikdown.net.readResponse
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.yield
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HttpRequestsTest {
    @Test
    fun cancelledRequestWaitsForItsReaderToReleaseTheFile() = runBlocking {
        val entered = CompletableDeferred<Unit>()
        val finishReading = CountDownLatch(1)
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                .code(200).message("OK").body("payload".toResponseBody()).build()
        }.build()
        val request = Request.Builder().url("https://example.test/video").build()
        val job = launch {
            client.readResponse(request) {
                entered.complete(Unit)
                finishReading.await(5, TimeUnit.SECONDS)
            }
        }
        try {
            withTimeout(3000) { entered.await() }
            job.cancel()
            // Let the cancelled coroutine resume while the callback is still holding the body.
            yield()
            assertFalse(job.isCompleted)
        } finally {
            finishReading.countDown()
            withTimeout(3000) { job.join() }
            client.dispatcher.executorService.shutdown()
        }
        assertTrue(job.isCancelled)
    }
}
