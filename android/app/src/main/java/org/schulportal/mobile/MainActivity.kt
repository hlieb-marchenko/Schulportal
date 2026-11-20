package org.schulportal.mobile

import android.app.Activity
import android.content.res.AssetManager
import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.TextView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.io.IOException
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
                val webRoot = copyWebAssets()
                val port = Python.getInstance()
                    .getModule("embedded_server")
                    .callAttr("start", webRoot.absolutePath)
                    .toInt()
                Log.i("Schulportal", "Embedded web app listening on port $port")

                runOnUiThread {
                    if (isFinishing || isDestroyed) {
                        return@runOnUiThread
                    }
                    webView = WebView(this).apply {
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true
                        settings.allowFileAccess = false
                        settings.allowContentAccess = false
                        webViewClient = object : WebViewClient() {
                            override fun shouldOverrideUrlLoading(
                                view: WebView,
                                request: WebResourceRequest,
                            ): Boolean {
                                val url = request.url
                                return url.scheme != "http" ||
                                    url.host != "127.0.0.1" ||
                                    url.port != port
                            }
                        }
                        CookieManager.getInstance().setAcceptCookie(true)
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
                Log.e("Schulportal", "Failed to start the embedded web app.", error)
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        status.text = "Could not start Schulportal: ${error.message}"
                    }
                }
            }
        }
    }

    private fun copyWebAssets(): File {
        val webRoot = File(filesDir, "web")
        if (!webRoot.exists() && !webRoot.mkdirs()) {
            throw IOException("Could not create the local web assets directory.")
        }
        copyAssetDirectory(assets, "web", webRoot)
        return webRoot
    }

    private fun copyAssetDirectory(assetManager: AssetManager, assetPath: String, destination: File) {
        val entries = assetManager.list(assetPath)
            ?: throw IOException("Could not read bundled web assets at $assetPath.")

        if (entries.isEmpty()) {
            destination.parentFile?.let {
                if (!it.exists() && !it.mkdirs()) {
                    throw IOException("Could not create directory ${it.absolutePath}.")
                }
            }
            assetManager.open(assetPath).use { input ->
                destination.outputStream().use { output -> input.copyTo(output) }
            }
            return
        }

        if (!destination.exists() && !destination.mkdirs()) {
            throw IOException("Could not create directory ${destination.absolutePath}.")
        }
        entries.forEach { entry ->
            copyAssetDirectory(assetManager, "$assetPath/$entry", File(destination, entry))
        }
    }

    override fun onDestroy() {
        executor.execute {
            if (Python.isStarted()) {
                try {
                    Python.getInstance().getModule("embedded_server").callAttr("stop")
                } catch (error: Exception) {
                    Log.e("Schulportal", "Failed to stop the embedded web server.", error)
                }
            }
        }
        executor.shutdown()
        if (::webView.isInitialized) {
            webView.destroy()
        }
        super.onDestroy()
    }
}
