(function () {
  var API_BASE_URL = "http://127.0.0.1:8000";

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

  window.TaxGlobalApi = {
    postCalc: postCalc,
    getStates: function () { return getJson("/api/states"); },
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
