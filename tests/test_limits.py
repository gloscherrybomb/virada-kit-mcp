from virada_kit import limits

def test_budget_per_client_and_reset():
    L = limits.Limiter(per_client=10, per_server=100, window=600)
    assert all(L.take('a', 'preview_kit', now=0) is None for _ in range(2))     # 8 of 10 units
    assert 'rate limit' in L.take('a', 'preview_kit', now=1)                    # 12 > 10
    assert L.take('b', 'preview_kit', now=1) is None                             # another client is fine
    assert L.take('a', 'preview_kit', now=700) is None                           # the window has passed

def test_server_wide_budget():
    L = limits.Limiter(per_client=100, per_server=8, window=600)
    assert L.take('a', 'export_kit', now=0) is None
    assert 'everyone' in L.take('b', 'get_kit_spec', now=1)

def test_client_address_from_proxy_headers():
    assert limits.client_of({'CF-Connecting-IP': '1.2.3.4', 'X-Forwarded-For': '9.9.9.9'}) == '1.2.3.4'
    assert limits.client_of({'x-forwarded-for': '5.6.7.8, 10.0.0.1'}) == '5.6.7.8'
    assert limits.client_of(None) == 'anonymous'
