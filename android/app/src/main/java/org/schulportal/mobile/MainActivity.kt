package org.schulportal.mobile

import android.app.Activity
import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.TextView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private val executor = Executors.newSingleThreadExecutor()
    private lateinit var status: TextView
    private lateinit var webView: WebView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        status = TextView(this).apply {
            gravity = Gravity.CENTER
            text = "Starting embedded Python…"
        }
        setContentView(
            status,
            ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )

        executor.execute {
            try {
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(applicationContext))
                }
                val port = Python.getInstance()
                    .getModule("embedded_server")
                    .callAttr("start")
                    .toInt()
                Log.i("Feasibility", "Loopback test server listening on port $port")

                runOnUiThread {
                    webView = WebView(this).apply {
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true
                        webViewClient = WebViewClient()
                        loadUrl("http://127.0.0.1:$port/")
                    }
                    setContentView(
                        webView,
                        ViewGroup.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.MATCH_PARENT,
                        ),
                    )
                }
            } catch (error: Exception) {
                runOnUiThread {
                    status.text = "Embedded backend failed: ${error.message}"
                }
            }
        }
    }

    override fun onDestroy() {
        executor.shutdownNow()
        if (::webView.isInitialized) {
            webView.destroy()
        }
        super.onDestroy()
    }
}
