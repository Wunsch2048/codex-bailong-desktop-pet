import unittest

from public_status import decode_status


def summary(*, components=(), incidents=(), indicator='minor'):
    return dict(status={'indicator': indicator}, components=list(components),
                incidents=list(incidents))


class CodexPublicStatusTests(unittest.TestCase):
    desktop = dict(id='desktop', name='Codex in ChatGPT Desktop', status='operational')

    def test_unrelated_incidents_do_not_warn_or_appear_in_details(self):
        result = decode_status(summary(components=[self.desktop], incidents=[
            dict(name='Elevated errors with image generation', status='monitoring'),
            dict(name='Payment outage', status='identified'),
        ]))
        self.assertEqual((result['tone'], result['incidents']), ('ok', []))

    def test_structured_codex_incident_is_reported_despite_global_indicator(self):
        result = decode_status(summary(components=[self.desktop], indicator='none', incidents=[
            dict(name='Elevated latency', status='investigating',
                 incident_updates=[dict(affected_components=[dict(code='desktop')])]),
        ]))
        self.assertEqual(result['title'], 'Codex 响应延迟')
        self.assertEqual(len(result['incidents']), 1)

    def test_codex_component_outage_without_incident_is_reported(self):
        result = decode_status(summary(components=[dict(self.desktop, status='major_outage')]))
        self.assertEqual(result['title'], 'Codex 服务有异常')

    def test_absent_codex_data_is_unknown_unless_incident_explicitly_names_it(self):
        self.assertEqual(decode_status(summary(indicator='none'))['tone'], 'unknown')
        result = decode_status(summary(incidents=[dict(name='Codex availability', status='monitoring')]))
        self.assertEqual(result['tone'], 'warn')

    def test_resolved_and_explicitly_unrelated_incidents_are_excluded(self):
        result = decode_status(summary(components=[self.desktop], incidents=[
            dict(name='Codex outage', status='resolved'),
            dict(name='Codex and image status', status='monitoring',
                 components=[dict(id='images', name='Image Generation')]),
        ]))
        self.assertEqual((result['tone'], result['incidents']), ('ok', []))
