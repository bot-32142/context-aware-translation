"""Tests for token tracking in DB layer."""

import tempfile
from pathlib import Path

import pytest

from context_aware_translation.storage.endpoint_profile import EndpointProfile
from context_aware_translation.storage.registry_db import RegistryDB


@pytest.fixture
def registry():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = RegistryDB(Path(tmpdir) / "test.db")
        yield db
        db.close()


def _make_profile(
    name="test",
    token_limit=None,
    tokens_used=0,
    input_token_limit=None,
    output_token_limit=None,
    input_tokens_used=0,
    output_tokens_used=0,
):
    import time
    import uuid

    return EndpointProfile(
        profile_id=uuid.uuid4().hex[:8],
        name=name,
        created_at=time.time(),
        updated_at=time.time(),
        api_key="key",
        base_url="https://api.test.com",
        model="model",
        token_limit=token_limit,
        tokens_used=tokens_used,
        input_token_limit=input_token_limit,
        output_token_limit=output_token_limit,
        input_tokens_used=input_tokens_used,
        output_tokens_used=output_tokens_used,
    )


class TestEndpointProfileTokenFields:
    """Test token tracking fields on EndpointProfile."""

    def test_default_values(self):
        import time

        ep = EndpointProfile(profile_id="x", name="x", created_at=time.time(), updated_at=time.time())
        assert ep.token_limit is None
        assert ep.tokens_used == 0
        assert ep.input_token_limit is None
        assert ep.output_token_limit is None
        assert ep.input_tokens_used == 0
        assert ep.output_tokens_used == 0
        assert ep.cached_input_tokens_used == 0
        assert ep.uncached_input_tokens_used == 0

    def test_to_dict_includes_token_fields(self):
        ep = _make_profile(
            token_limit=1000,
            tokens_used=500,
            input_token_limit=600,
            output_token_limit=400,
            input_tokens_used=300,
            output_tokens_used=200,
        )
        ep.cached_input_tokens_used = 120
        ep.uncached_input_tokens_used = 180
        d = ep.to_dict()
        assert d["token_limit"] == 1000
        assert d["tokens_used"] == 500
        assert d["input_token_limit"] == 600
        assert d["output_token_limit"] == 400
        assert d["input_tokens_used"] == 300
        assert d["output_tokens_used"] == 200
        assert d["cached_input_tokens_used"] == 120
        assert d["uncached_input_tokens_used"] == 180

    def test_from_dict_round_trip(self):
        ep = _make_profile(
            token_limit=5000,
            tokens_used=2500,
            input_token_limit=3000,
            output_token_limit=2000,
            input_tokens_used=1500,
            output_tokens_used=1000,
        )
        ep.cached_input_tokens_used = 600
        ep.uncached_input_tokens_used = 900
        d = ep.to_dict()
        ep2 = EndpointProfile.from_dict(d)
        assert ep2.token_limit == 5000
        assert ep2.tokens_used == 2500
        assert ep2.input_token_limit == 3000
        assert ep2.output_token_limit == 2000
        assert ep2.input_tokens_used == 1500
        assert ep2.output_tokens_used == 1000
        assert ep2.cached_input_tokens_used == 600
        assert ep2.uncached_input_tokens_used == 900

    def test_from_dict_defaults(self):
        import time

        d = {
            "profile_id": "x",
            "name": "x",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        ep = EndpointProfile.from_dict(d)
        assert ep.token_limit is None
        assert ep.tokens_used == 0
        assert ep.input_token_limit is None
        assert ep.output_token_limit is None
        assert ep.input_tokens_used == 0
        assert ep.output_tokens_used == 0
        assert ep.cached_input_tokens_used == 0
        assert ep.uncached_input_tokens_used == 0


class TestDBTokenTracking:
    """Test DB-level token operations."""

    def test_insert_with_token_limit(self, registry):
        ep = _make_profile(token_limit=10000)
        registry.insert_endpoint_profile(ep)
        loaded = registry.get_endpoint_profile(ep.profile_id)
        assert loaded is not None
        assert loaded.token_limit == 10000
        assert loaded.tokens_used == 0

    def test_insert_without_token_limit(self, registry):
        ep = _make_profile()
        registry.insert_endpoint_profile(ep)
        loaded = registry.get_endpoint_profile(ep.profile_id)
        assert loaded is not None
        assert loaded.token_limit is None
        assert loaded.tokens_used == 0

    def test_insert_with_all_limits(self, registry):
        ep = _make_profile(token_limit=10000, input_token_limit=6000, output_token_limit=4000)
        registry.insert_endpoint_profile(ep)
        loaded = registry.get_endpoint_profile(ep.profile_id)
        assert loaded is not None
        assert loaded.token_limit == 10000
        assert loaded.input_token_limit == 6000
        assert loaded.output_token_limit == 4000
        assert loaded.input_tokens_used == 0
        assert loaded.output_tokens_used == 0

    def test_increment_endpoint_tokens(self, registry):
        ep = _make_profile(token_limit=10000)
        registry.insert_endpoint_profile(ep)

        updated = registry.increment_endpoint_tokens(ep.profile_id, 500)
        assert updated is not None
        assert updated.tokens_used == 500

        updated = registry.increment_endpoint_tokens(ep.profile_id, 300)
        assert updated is not None
        assert updated.tokens_used == 800

    def test_increment_endpoint_tokens_with_breakdown(self, registry):
        ep = _make_profile(token_limit=10000, input_token_limit=6000, output_token_limit=4000)
        registry.insert_endpoint_profile(ep)

        updated = registry.increment_endpoint_tokens(
            ep.profile_id,
            500,
            input_tokens=300,
            output_tokens=200,
            cached_input_tokens=100,
            uncached_input_tokens=200,
        )
        assert updated is not None
        assert updated.tokens_used == 500
        assert updated.input_tokens_used == 300
        assert updated.output_tokens_used == 200
        assert updated.cached_input_tokens_used == 100
        assert updated.uncached_input_tokens_used == 200

        updated = registry.increment_endpoint_tokens(
            ep.profile_id,
            300,
            input_tokens=100,
            output_tokens=200,
            cached_input_tokens=50,
            uncached_input_tokens=50,
        )
        assert updated is not None
        assert updated.tokens_used == 800
        assert updated.input_tokens_used == 400
        assert updated.output_tokens_used == 400
        assert updated.cached_input_tokens_used == 150
        assert updated.uncached_input_tokens_used == 250

    def test_reset_endpoint_tokens(self, registry):
        ep = _make_profile(token_limit=10000)
        registry.insert_endpoint_profile(ep)
        registry.increment_endpoint_tokens(
            ep.profile_id,
            5000,
            input_tokens=3000,
            output_tokens=2000,
            cached_input_tokens=1000,
            uncached_input_tokens=2000,
        )

        updated = registry.reset_endpoint_tokens(ep.profile_id)
        assert updated is not None
        assert updated.tokens_used == 0
        assert updated.input_tokens_used == 0
        assert updated.output_tokens_used == 0
        assert updated.cached_input_tokens_used == 0
        assert updated.uncached_input_tokens_used == 0

    def test_update_token_limit(self, registry):
        ep = _make_profile()
        registry.insert_endpoint_profile(ep)

        updated = registry.update_endpoint_profile(ep.profile_id, token_limit=50000)
        assert updated is not None
        assert updated.token_limit == 50000

    def test_update_input_output_limits(self, registry):
        ep = _make_profile()
        registry.insert_endpoint_profile(ep)

        updated = registry.update_endpoint_profile(ep.profile_id, input_token_limit=30000, output_token_limit=20000)
        assert updated is not None
        assert updated.input_token_limit == 30000
        assert updated.output_token_limit == 20000

    def test_row_to_endpoint_profile_includes_token_fields(self, registry):
        ep = _make_profile(token_limit=1000, tokens_used=0)
        registry.insert_endpoint_profile(ep)
        registry.increment_endpoint_tokens(
            ep.profile_id,
            250,
            input_tokens=150,
            output_tokens=100,
            cached_input_tokens=50,
            uncached_input_tokens=100,
        )

        loaded = registry.get_endpoint_profile(ep.profile_id)
        assert loaded is not None
        assert loaded.token_limit == 1000
        assert loaded.tokens_used == 250
        assert loaded.input_tokens_used == 150
        assert loaded.output_tokens_used == 100
        assert loaded.cached_input_tokens_used == 50
        assert loaded.uncached_input_tokens_used == 100
