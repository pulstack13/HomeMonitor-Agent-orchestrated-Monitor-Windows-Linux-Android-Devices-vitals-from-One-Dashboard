package com.homemonitor.lite;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * Full-screen wrapper for the read-only HomeMonitor lite dashboard.
 *
 * The admin token is only used when the activity is launched with
 * {@code --es token <token>}: it is typed into the page once and then dropped
 * from memory. Afterwards the HttpOnly session cookie is managed by WebView.
 */
public class MainActivity extends Activity {
    private static final String START_URL = "http://127.0.0.1:8787/lite";

    private WebView webView;
    private LinearLayout errorView;
    private String pendingToken;
    private boolean loadFailed;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable flushCookies = new Runnable() {
        @Override
        public void run() {
            CookieManager.getInstance().flush();
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);

        Intent intent = getIntent();
        pendingToken = intent.getStringExtra("token");
        intent.removeExtra("token");

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        webView = new WebView(this);
        webView.setBackgroundColor(Color.BLACK);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setMediaPlaybackRequiresUserGesture(true);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            cookies.setAcceptThirdPartyCookies(webView, true);
        }

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                loadFailed = false;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (loadFailed) return;
                hideError();
                view.scrollTo(0, 0);
                // The FULL link targets the desktop dashboard, which this old WebView cannot render.
                view.evaluateJavascript(
                        "var a=document.querySelector('.head-right a');if(a){a.style.display='none';}",
                        null);
                // Persist the session cookie even if the process is killed before onPause.
                handler.removeCallbacks(flushCookies);
                handler.postDelayed(flushCookies, 1200);
                handler.postDelayed(flushCookies, 3500);
                if (pendingToken != null) {
                    String token = pendingToken;
                    pendingToken = null;
                    String script = "(function(){"
                            + "var t=document.getElementById('token');"
                            + "var f=document.getElementById('login-form');"
                            + "var l=document.getElementById('login');"
                            + "if(t&&f&&l&&!l.hidden){"
                            + "t.value=" + JSONObject.quote(token) + ";"
                            + "var e=document.createEvent('Event');"
                            + "e.initEvent('submit',true,true);"
                            + "f.dispatchEvent(e);"
                            + "}})();";
                    view.evaluateJavascript(script, null);
                }
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                if (failingUrl != null && failingUrl.startsWith(START_URL)) {
                    loadFailed = true;
                    showError();
                }
            }
        });

        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        errorView = new LinearLayout(this);
        errorView.setOrientation(LinearLayout.VERTICAL);
        errorView.setBackgroundColor(Color.BLACK);
        errorView.setGravity(Gravity.CENTER);
        errorView.setPadding(32, 32, 32, 32);
        errorView.setVisibility(View.GONE);

        TextView title = new TextView(this);
        title.setText("CONTROLLER OFFLINE");
        title.setTextColor(Color.parseColor("#FF6B6B"));
        title.setTextSize(18);
        title.setGravity(Gravity.CENTER);

        TextView detail = new TextView(this);
        detail.setText("Cannot reach 127.0.0.1:8787/lite");
        detail.setTextColor(Color.parseColor("#5B6F63"));
        detail.setTextSize(12);
        detail.setGravity(Gravity.CENTER);
        detail.setPadding(0, 12, 0, 20);

        Button retry = new Button(this);
        retry.setText("RETRY");
        retry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                loadFailed = false;
                hideError();
                webView.reload();
            }
        });

        errorView.addView(title);
        errorView.addView(detail);
        errorView.addView(retry);
        root.addView(errorView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        setContentView(root);
        webView.loadUrl(START_URL);
    }

    private void showError() {
        if (errorView != null) errorView.setVisibility(View.VISIBLE);
    }

    private void hideError() {
        if (errorView != null) errorView.setVisibility(View.GONE);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
            webView.resumeTimers();
        }
        hideSystemUi();
    }

    @Override
    protected void onPause() {
        if (webView != null) {
            CookieManager.getInstance().flush();
            webView.onPause();
        }
        super.onPause();
    }

    @Override
    protected void onStop() {
        CookieManager.getInstance().flush();
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(flushCookies);
        if (webView != null) {
            webView.loadUrl("about:blank");
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        }
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemUi();
    }

    private void hideSystemUi() {
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
    }
}
