package com.chentzer.fincomp;

import android.Manifest;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.webkit.WebView;
import androidx.core.content.ContextCompat;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

/**
 * Upload in the background: the web app calls start() when an upload
 * begins, update() as it goes and stop() when it ends. While it runs,
 * UploadService keeps the app alive with a progress notification, and the
 * page keeps full priority even when it can't be seen.
 */
@CapacitorPlugin(
    name = "UploadKeeper",
    permissions = { @Permission(alias = "notifications", strings = { Manifest.permission.POST_NOTIFICATIONS }) }
)
public class UploadKeeperPlugin extends Plugin {

    @PluginMethod
    public void start(PluginCall call) {
        // Android 13+: the progress notification needs permission (asked once; the upload runs either way).
        if (Build.VERSION.SDK_INT >= 33 && getPermissionState("notifications") != PermissionState.GRANTED) {
            requestPermissionForAlias("notifications", call, "afterPermission");
            return;
        }
        begin(call);
    }

    @PermissionCallback
    private void afterPermission(PluginCall call) {
        begin(call);
    }

    private void begin(PluginCall call) {
        Context ctx = getContext();
        Intent i = new Intent(ctx, UploadService.class)
                .putExtra(UploadService.EXTRA_TEXT, call.getString("text", "Starting"))
                .putExtra(UploadService.EXTRA_PERCENT, call.getInt("percent", -1));
        try {
            ContextCompat.startForegroundService(ctx, i);
        } catch (Exception e) {
            // Android refused (e.g. started from the background): the upload still runs while the app is open.
            call.resolve();
            return;
        }
        keepPageAwake(true);
        call.resolve();
    }

    @PluginMethod
    public void update(PluginCall call) {
        UploadService.ensureChannel(getContext());
        NotificationManager nm = (NotificationManager) getContext().getSystemService(Context.NOTIFICATION_SERVICE);
        nm.notify(UploadService.ONGOING_ID, UploadService.build(getContext(),
                call.getString("text", ""), call.getInt("percent", -1), true));
        call.resolve();
    }

    @PluginMethod
    public void stop(PluginCall call) {
        Context ctx = getContext();
        ctx.stopService(new Intent(ctx, UploadService.class));
        keepPageAwake(false);
        String done = call.getString("text");
        // Say it finished, but only if you're not looking at the app.
        if (done != null && !getBridge().getActivity().hasWindowFocus()) {
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            nm.notify(UploadService.DONE_ID, UploadService.build(ctx, done, 100, false));
        }
        call.resolve();
    }

    /** The page's renderer keeps its priority while hidden, so the upload isn't paused or killed. */
    private void keepPageAwake(boolean on) {
        if (Build.VERSION.SDK_INT < 26) return;
        getActivity().runOnUiThread(() -> {
            WebView w = getBridge().getWebView();
            w.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, !on);
        });
    }
}
