(function () {
  // Match the page host so the API is same-site with the frontend (localhost vs
  // 127.0.0.1 are different sites — a mismatch blocks the SameSite=Lax session
  // cookie). Falls back to 127.0.0.1 when opened without a host (file://).
  var API_HOST = (window.location && window.location.hostname) || "127.0.0.1";
  var API_BASE_URL = "http://" + API_HOST + ":8000";

  function makeApiError(message, options) {
    var error = new Error(message);
    options = options || {};
    error.name = "ApiError";
    error.code = options.code || "api_error";
    error.status = options.status || null;
    error.details = options.details || [];
    return error;
  }

  function postCalc(path, payload) {
    return window.fetch(API_BASE_URL + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .catch(function (error) {
        throw makeApiError("Backend service is unavailable.", {
          code: "service_unavailable",
          details: [String(error && error.message ? error.message : error)],
        });
      })
      .then(function (response) {
        return response.json().catch(function () {
          return null;
        }).then(function (body) {
          if (!response.ok) {
            var apiError = body && body.error ? body.error : {};
            throw makeApiError(apiError.message || "Backend request failed.", {
              code: apiError.code || "request_failed",
              status: response.status,
              details: apiError.details || [],
            });
          }
          if (!body || typeof body.status !== "string") {
            throw makeApiError("Server returned an unexpected response.", {
              code: "invalid_response",
              status: response.status,
            });
          }
          return body;
        });
      });
  }

  function getJson(path) {
    return window.fetch(API_BASE_URL + path)
      .catch(function (error) {
        throw makeApiError("Backend service is unavailable.", {
          code: "service_unavailable",
          details: [String(error && error.message ? error.message : error)],
        });
      })
      .then(function (response) {
        return response.json().catch(function () {
          return null;
        }).then(function (body) {
          if (!response.ok) {
            var apiError = body && body.error ? body.error : {};
            throw makeApiError(apiError.message || "Backend request failed.", {
              code: apiError.code || "request_failed",
              status: response.status,
              details: apiError.details || [],
            });
          }
          if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).length === 0) {
            throw makeApiError("Server returned an unexpected response.", {
              code: "invalid_response",
              status: response.status,
            });
          }
          return body;
        });
      });
  }

  function authFetch(path, options) {
    var opts = Object.assign({ credentials: "include" }, options || {});
    return window.fetch(API_BASE_URL + path, opts).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        return { status: response.status, ok: response.ok, body: body };
      });
    });
  }

  window.TaxGlobalApi = {
    postCalc: postCalc,
    getStates: function () { return getJson("/api/states"); },
    authMe: function () { return authFetch("/api/auth/me"); },
    devLogin: function (email, name) {
      return authFetch("/api/auth/dev-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email, name: name || "" }),
      });
    },
    logout: function () { return authFetch("/api/auth/logout", { method: "POST" }); },
    providerLoginUrl: function (provider) { return API_BASE_URL + "/api/auth/" + provider + "/login"; },
    // Detect whether a provider's OAuth is configured: a configured server
    // 302-redirects (opaqueredirect under redirect:manual); otherwise 503 JSON.
    providerConfigured: function (provider) {
      return window.fetch(API_BASE_URL + "/api/auth/" + provider + "/login", {
        credentials: "include",
        redirect: "manual",
      }).then(function (response) {
        return response.type === "opaqueredirect" || response.status === 0 || response.status === 302;
      }).catch(function () { return false; });
    },
    connectors: function () { return getJson("/api/connectors"); },
    // The connector evaluation has its own response shape (not the engine
    // _response envelope), so it does not go through postCalc's status check.
    connectorNexus: function (platform, payload) {
      return authFetch("/api/connectors/" + platform + "/nexus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(function (r) {
        if (!r.ok) {
          var e = (r.body && r.body.error) || {};
          throw makeApiError(e.message || "Connector request failed.", { code: e.code || "request_failed", status: r.status });
        }
        return r.body;
      });
    },
    federalIncome: function (payload) { return postCalc("/calc/federal-income", payload); },
    fica: function (payload) { return postCalc("/calc/fica", payload); },
    stateIncome: function (payload) { return postCalc("/calc/state-income", payload); },
    incomeSummary: function (payload) { return postCalc("/calc/income-summary", payload); },
    nexus: function (payload) { return postCalc("/calc/nexus", payload); },
    crypto: function (payload) { return postCalc("/calc/crypto", payload); },
    feie: function (payload) { return postCalc("/calc/feie", payload); },
    rsu: function (payload) {
      var apiPayload = Object.assign({}, payload);
      if (typeof apiPayload.fair_market_value_per_share !== "undefined") {
        apiPayload.fmv_per_share = apiPayload.fair_market_value_per_share;
        delete apiPayload.fair_market_value_per_share;
      }
      return postCalc("/calc/rsu", apiPayload);
    },
  };
}());
