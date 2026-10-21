import asyncio
import copy
import unittest
from unittest.mock import AsyncMock
from aurora_assistant.mcp_client import Consent, MCPFailure, canonical

REQUEST = {'contract': 'aurora-mcdbus-1', 'bus': 'session', 'service': 'org.kde.Test',
           'owner': ':1.2', 'object_path': '/', 'interface': 'org.kde.Test',
           'method': 'SetLevel', 'args': [50], 'signature': 'i'}
PLAN = {'action': {'name': 'dbus_call', 'argument': 'test'}, 'requires_approval': True}


class ConsentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100.
        self.prompt = AsyncMock(return_value=True)
        self.consent = Consent(self.prompt, clock=lambda: self.now)
        self.plan = self.consent.prepare(PLAN, REQUEST)

    def begin(self):
        self.consent.authorize([self.plan])
        return self.consent.begin(self.plan)

    async def test_no_model_or_unapproved_grant(self):
        with self.assertRaisesRegex(MCPFailure, 'invalid_consent'):
            self.consent.begin(self.plan)
        self.assertFalse(await self.consent.elicit(canonical(REQUEST)))

    async def test_exact_session_consent_is_single_use(self):
        request = self.begin()
        self.assertTrue(await self.consent.elicit(canonical(request)))
        self.assertFalse(await self.consent.elicit(canonical(request)))
        self.prompt.assert_not_awaited()
        self.consent.finish()
        with self.assertRaises(MCPFailure):
            self.consent.begin(self.plan)

    async def test_every_request_field_is_bound(self):
        request = self.begin()
        for key in request:
            changed = copy.deepcopy(request)
            changed[key] = 'different'
            with self.subTest(key=key):
                self.assertFalse(await self.consent.elicit(canonical(changed)))
        self.assertTrue(await self.consent.elicit(canonical(request)))

    async def test_boolean_does_not_equal_integer(self):
        request = self.begin()
        changed = {**request, 'args': [True]}
        self.assertFalse(await self.consent.elicit(canonical(changed)))

    async def test_malformed_duplicate_and_extra_fields_deny(self):
        request = self.begin()
        for text in ['{', canonical(request)[:-1] + ',"bus":"session"}',
                     canonical({**request, 'extra': True}), 'NaN', 'x' * 16385]:
            self.assertFalse(await self.consent.elicit(text))

    async def test_expired_before_authorization_or_confirmation(self):
        self.now = 220.
        with self.assertRaises(MCPFailure):
            self.consent.authorize([self.plan])
        self.now = 100.
        request = self.begin()
        self.now = 220.
        self.assertFalse(await self.consent.elicit(canonical(request)))

    async def test_changed_plan_or_expiry_cannot_be_authorized(self):
        for key, value in [('expires_at', 9999), ('requires_approval', False), ('action', {})]:
            changed = {**self.plan, key: value}
            with self.subTest(key=key), self.assertRaises(MCPFailure):
                self.consent.authorize([changed])

    async def test_system_requires_second_explicit_approval(self):
        plan = self.consent.prepare(PLAN, {**REQUEST, 'bus': 'system'})
        self.consent.authorize([plan])
        request = self.consent.begin(plan)
        self.assertTrue(await self.consent.elicit(canonical(request)))
        self.prompt.assert_awaited_once_with(request)

    async def test_system_denial_timeout_and_expiry_deny(self):
        for response in [False, 1, None, TimeoutError()]:
            with self.subTest(response=response):
                self.consent.finish()
                plan = self.consent.prepare(PLAN, {**REQUEST, 'bus': 'system'})
                self.consent.authorize([plan])
                request = self.consent.begin(plan)
                self.prompt.side_effect = response if isinstance(response, Exception) else None
                self.prompt.return_value = response
                self.assertFalse(await self.consent.elicit(canonical(request)))
                self.assertFalse(self.consent.active['accepted'])

    async def test_cancel_and_revoke_clear_remaining_grants(self):
        request = self.begin()
        self.consent.finish()
        self.assertFalse(await self.consent.elicit(canonical(request)))
        plan = self.consent.prepare(PLAN, REQUEST)
        self.consent.authorize([plan])
        self.consent.revoke([plan])
        with self.assertRaises(MCPFailure):
            self.consent.begin(plan)

    async def test_bound_and_duplicate_plans(self):
        for plans in [[], [self.plan] * 2, [self.plan] * 5]:
            with self.assertRaises(MCPFailure):
                self.consent.authorize(plans)
