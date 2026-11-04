package com.chentzer.fincomp;

import android.accounts.Account;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.google.android.gms.auth.api.identity.AuthorizationClient;
import com.google.android.gms.auth.api.identity.AuthorizationRequest;
import com.google.android.gms.auth.api.identity.ClearTokenRequest;
import com.google.android.gms.auth.api.identity.Identity;
import com.google.android.gms.common.api.Scope;
import java.util.ArrayList;
import java.util.List;

/**
 * A new access token for the account you already signed in with, with no
 * account chooser: Android's AuthorizationClient answers without any screen
 * once that account has allowed these scopes. The sign-in plugin always goes
 * through the chooser first, which is why reopening the app used to ask again.
 * Rejects when it would need a screen; NativeAuth then falls back to the plugin.
 */
@CapacitorPlugin(name = "QuietToken")
public class QuietTokenPlugin extends Plugin {

    @PluginMethod
    public void get(PluginCall call) {
        String email = call.getString("email");
        JSArray names = call.getArray("scopes");
        List<Scope> scopes = new ArrayList<>();
        try {
            for (int i = 0; i < names.length(); i++) scopes.add(new Scope(names.getString(i)));
        } catch (Exception e) {
            call.reject("Bad scopes");
            return;
        }
        if (email == null || email.isEmpty() || scopes.isEmpty()) {
            call.reject("Needs an account and scopes");
            return;
        }
        AuthorizationClient client = Identity.getAuthorizationClient(getContext());
        String refused = call.getString("refused");
        if (refused != null && !refused.isEmpty()) {
            // Google refused this token, but Android would hand the same one back: clear it first.
            ClearTokenRequest clear = ClearTokenRequest.builder().setToken(refused).build();
            client.clearToken(clear)
                .addOnSuccessListener((v) -> authorize(client, call, email, scopes))
                .addOnFailureListener((e) -> authorize(client, call, email, scopes));
            return;
        }
        authorize(client, call, email, scopes);
    }

    private void authorize(AuthorizationClient client, PluginCall call, String email, List<Scope> scopes) {
        AuthorizationRequest request = AuthorizationRequest.builder()
            .setRequestedScopes(scopes)
            .setAccount(new Account(email, "com.google"))
            .build();
        client
            .authorize(request)
            .addOnSuccessListener((result) -> {
                if (result.hasResolution() || result.getAccessToken() == null) {
                    call.reject("Needs a screen");
                    return;
                }
                JSObject out = new JSObject();
                out.put("token", result.getAccessToken());
                call.resolve(out);
            })
            .addOnFailureListener((e) -> call.reject("Could not renew: " + e.getMessage()));
    }
}
