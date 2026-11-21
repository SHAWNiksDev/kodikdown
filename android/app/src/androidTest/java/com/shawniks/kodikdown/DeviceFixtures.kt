package com.shawniks.kodikdown

import android.util.Log
import java.util.UUID

internal fun qaDownloadDirectory(): String =
    "Download/KodikDown-Device-QA-${UUID.randomUUID()}".also { Log.i("KodikDownDeviceQA", it) }
