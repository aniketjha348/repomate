# Network attempt is blocked by the verification sandbox

- **Case:** `network_tabulate_scripted`
- **Repository:** `astanin/python-tabulate`
- **Input:** https://github.com/astanin/python-tabulate — “Document how the network regression test is expected to behave.”
- **Upstream commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Prepared commit:** `8d0ab6b20716cf69c03139c8ca15777723d89c1f`
- **Planner observed:** `scripted-eval-v1`
- **Status:** `COMPLETED`
- **Expected:** COMPLETED with a DOCS_DIFF; the injected egress test FAILS and the receipt shows a verified sandbox policy
- **Verdict:** PASS — sandbox=disabled/bwrap, egress=PASSED; suite=FAILED

## Injected test / fault

Committed a test that requires public HTTPS. A correctly enforcing sandbox must make it fail.

- `test/test_network_egress.py`

## Retrieval

- **Status:** `COMPLETE`
- **Files:** 19 examined of 19 eligible (27 tracked)
- **Evidence records:** 8
- **Summary:** Retrieval is COMPLETE: examined 19 of 19 eligible file(s) from 27 tracked file(s), read 369795 byte(s), and retained 14 matching file(s). No retrieval limit was reached.


## Artifact

- **Kind:** `DOCS_DIFF`
- **Paths:** `README.md`
- **Patch lines:** 12

## Documents

- `CONTRIBUTION_PLAN.md` (CONTRIBUTION_PLAN)

## Receipt

| Check | Status | Detail |
|---|---|---|
| `patch-path-policy` | `PASSED` |  |
| `patch-applies-on-pinned-commit` | `PASSED` |  |
| `sandbox-egress-isolation` | `PASSED` | every egress attempt from inside the sandbox was refused |
| `repository-test-suite` | `FAILED` | iven') # will parse host:port h = http_class(host, timeout=req.timeout, **http_conn_args) h.set_debuglevel(self._debuglevel) headers = dict(req.unredirected_hdrs) headers.update({k |

## Comparison

- **Outcome:** `UNRESOLVED`
- **Baseline:** `FAILED`
- **Post-patch:** `FAILED`
- **Interpretation:** the selected check failed before and after the patch; the failure is unresolved or a different failure is present

### Baseline output tail

```
tion"] = "close"
        headers = {name.title(): val for name, val in headers.items()}
    
        if req._tunnel_host:
            tunnel_headers = {}
            proxy_auth_hdr = "Proxy-Authorization"
            if proxy_auth_hdr in headers:
                tunnel_headers[proxy_auth_hdr] = headers[proxy_auth_hdr]
                # Proxy-Authorization should not be sent to origin
                # server.
                del headers[proxy_auth_hdr]
            h.set_tunnel(req._tunnel_host, headers=tunnel_headers)
    
        try:
            try:
                h.request(req.get_method(), req.selector, req.data, headers,
                          encode_chunked=req.has_header('Transfer-encoding'))
            except OSError as err: # timeout error
>               raise URLError(err)
E               urllib.error.URLError: <urlopen error [Errno -3] Temporary failure in name resolution>

/usr/lib/python3.14/urllib/request.py:1324: URLError
=========================== short test summary info ============================
FAILED test/test_network_egress.py::test_public_https_is_reachable - urllib.e...
================== 1 failed, 366 passed, 17 skipped in 4.89s ===================
```

### Post-patch output tail

```
tion"] = "close"
        headers = {name.title(): val for name, val in headers.items()}
    
        if req._tunnel_host:
            tunnel_headers = {}
            proxy_auth_hdr = "Proxy-Authorization"
            if proxy_auth_hdr in headers:
                tunnel_headers[proxy_auth_hdr] = headers[proxy_auth_hdr]
                # Proxy-Authorization should not be sent to origin
                # server.
                del headers[proxy_auth_hdr]
            h.set_tunnel(req._tunnel_host, headers=tunnel_headers)
    
        try:
            try:
                h.request(req.get_method(), req.selector, req.data, headers,
                          encode_chunked=req.has_header('Transfer-encoding'))
            except OSError as err: # timeout error
>               raise URLError(err)
E               urllib.error.URLError: <urlopen error [Errno -3] Temporary failure in name resolution>

/usr/lib/python3.14/urllib/request.py:1324: URLError
=========================== short test summary info ============================
FAILED test/test_network_egress.py::test_public_https_is_reachable - urllib.e...
================== 1 failed, 366 passed, 17 skipped in 4.63s ===================
```

## Provenance

- Case workspace: `var/eval-real/cases/network_tabulate_scripted`
- Elapsed: 15.47s
- Sandbox backend: `bwrap`
- Planner requested: `scripted`

## Notes

The injected test tries to reach https://example.com. Under bubblewrap the suite fails; when no enforcing backend exists the sandbox must refuse with NOT_RUN instead.
