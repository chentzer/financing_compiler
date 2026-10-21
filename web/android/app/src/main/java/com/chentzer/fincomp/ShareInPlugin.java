package com.chentzer.fincomp;

import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.util.Base64;
import android.webkit.MimeTypeMap;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * "Share to FinMerge": statements (PDF), Splitwise exports (CSV) and accounts
 * workbooks (XLSX) shared from another app arrive here. MainActivity hands
 * each share intent to receive(); the web app takes the files with take()
 * (on start, and whenever the "shared" event fires) and uploads them.
 */
@CapacitorPlugin(name = "ShareIn")
public class ShareInPlugin extends Plugin {

    private static final List<JSObject> pending = new ArrayList<>();
    private static ShareInPlugin instance;

    @Override
    public void load() {
        instance = this;
    }

    /** Files from a share intent (one or several); anything else is ignored. */
    static void receive(Context context, Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        List<Uri> uris = new ArrayList<>();
        if (Intent.ACTION_SEND.equals(action)) {
            Uri uri = intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (uri != null) uris.add(uri);
        } else if (Intent.ACTION_SEND_MULTIPLE.equals(action)) {
            ArrayList<Uri> list = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (list != null) uris.addAll(list);
        } else {
            return;
        }
        ContentResolver resolver = context.getContentResolver();
        synchronized (pending) {
            for (Uri uri : uris) {
                try (InputStream in = resolver.openInputStream(uri)) {
                    if (in == null) continue;
                    ByteArrayOutputStream out = new ByteArrayOutputStream();
                    byte[] buf = new byte[64 * 1024];
                    int n;
                    while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                    JSObject file = new JSObject();
                    file.put("name", fileName(resolver, uri));
                    file.put("data", Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP));
                    pending.add(file);
                } catch (Exception e) {
                    // Unreadable share: skip it; the others still come through.
                }
            }
        }
        // Handled once: rotating the screen must not share the same files again.
        intent.setAction(Intent.ACTION_MAIN);
        if (instance != null) instance.notifyListeners("shared", new JSObject(), true);
    }

    /** The file's own name, with an extension the app can recognise (.pdf, .csv, .xlsx). */
    private static String fileName(ContentResolver resolver, Uri uri) {
        String name = null;
        try (Cursor c = resolver.query(uri, new String[] {OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst()) name = c.getString(0);
        } catch (Exception e) {
            // fall back below
        }
        if (name == null || name.isEmpty()) name = uri.getLastPathSegment();
        if (name == null || name.isEmpty()) name = "shared";
        if (!name.contains(".")) {
            String ext = MimeTypeMap.getSingleton().getExtensionFromMimeType(resolver.getType(uri));
            name = name + "." + (ext != null ? ext : "pdf");
        }
        return name;
    }

    @PluginMethod
    public void take(PluginCall call) {
        JSArray files = new JSArray();
        synchronized (pending) {
            for (JSObject f : pending) files.put(f);
            pending.clear();
        }
        JSObject result = new JSObject();
        result.put("files", files);
        call.resolve(result);
    }
}
