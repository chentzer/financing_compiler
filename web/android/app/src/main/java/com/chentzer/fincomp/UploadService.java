package com.chentzer.fincomp;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;

/**
 * Keeps FinMerge running while an upload is in progress, so switching apps
 * or turning the screen off doesn't stop it. Android only lets an app work
 * in the background like this while it shows a notification: this one has
 * the upload's progress and opens the app when tapped. UploadKeeperPlugin
 * starts, updates and stops it.
 */
public class UploadService extends Service {

    static final String CHANNEL = "uploads";
    static final int ONGOING_ID = 41;
    static final int DONE_ID = 42;
    static final String EXTRA_TEXT = "text";
    static final String EXTRA_PERCENT = "percent";

    private PowerManager.WakeLock wakeLock;

    static void ensureChannel(Context context) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = context.getSystemService(NotificationManager.class);
        if (nm.getNotificationChannel(CHANNEL) != null) return;
        NotificationChannel ch = new NotificationChannel(CHANNEL, "Uploads", NotificationManager.IMPORTANCE_LOW);
        ch.setDescription("Progress of statement uploads");
        nm.createNotificationChannel(ch);
    }

    static Notification build(Context context, String text, int percent, boolean ongoing) {
        Intent open = new Intent(context, MainActivity.class).setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent tap = PendingIntent.getActivity(context, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder b = new NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_upload)
                .setContentTitle(ongoing ? "Uploading to FinMerge" : "FinMerge upload finished")
                .setContentText(text)
                .setContentIntent(tap)
                .setOnlyAlertOnce(true)
                .setOngoing(ongoing)
                .setAutoCancel(!ongoing)
                .setCategory(NotificationCompat.CATEGORY_PROGRESS);
        if (ongoing) b.setProgress(100, Math.max(0, Math.min(100, percent)), percent < 0);
        return b.build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        ensureChannel(this);
        String text = intent != null && intent.getStringExtra(EXTRA_TEXT) != null ? intent.getStringExtra(EXTRA_TEXT) : "Starting";
        int percent = intent != null ? intent.getIntExtra(EXTRA_PERCENT, -1) : -1;
        Notification n = build(this, text, percent, true);
        int type = Build.VERSION.SDK_INT >= 29 ? ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC : 0;
        ServiceCompat.startForeground(this, ONGOING_ID, n, type);
        if (wakeLock == null) {
            // The CPU keeps going with the screen off; released when the upload ends (or after 30 min at most).
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "FinMerge:upload");
            wakeLock.acquire(30 * 60 * 1000L);
        }
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        wakeLock = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
