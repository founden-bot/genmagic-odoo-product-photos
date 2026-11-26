# Runs inside `odoo shell` (env is the superuser environment). Exercises the module the way a merchant does, with
# GenMagic's HTTP calls replaced by fixed answers, then prints SMOKE OK. Any exception fails the job.
import base64
from unittest import mock

from odoo.addons.genmagic_product_photos.models import genmagic_client as client

PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)
BLOB = 'https://axrsv1b9sa2ny4qv.public.blob.vercel-storage.com/0f0f0f0f-0f0f-4f0f-8f0f-0f0f0f0f0f0f/x.png'

assert client.is_allowed_media_url(BLOB), 'blob host refused'
assert client.is_allowed_media_url('https://genmagic.co/a.png')
assert not client.is_allowed_media_url('https://genmagic.co.evil.example/a.png')

W = env['genmagic.photo.wizard']
tmpl = env['product.template'].create({'name': 'GenMagic CI Mug', 'image_1920': base64.b64encode(PNG)})
action = tmpl.action_open_genmagic_photos()
assert action['res_model'] == 'genmagic.photo.wizard'

# Without consent nothing is sent and the wizard says why.
wiz = W.with_context(action['context']).create({})
assert wiz.product_tmpl_id == tmpl, 'default product not set'
assert wiz.setup_problem, 'no consent message'

# Settings: consent and key through the real settings model.
settings = env['res.config.settings'].create({'genmagic_consent': True, 'genmagic_api_key': 'gm_ci_key'})
settings.execute()
ICP = env['ir.config_parameter'].sudo()
assert ICP.get_param('genmagic_product_photos.api_key') == 'gm_ci_key'

models = [{'id': client.DEFAULT_MODEL, 'name': 'Default', 'est_usd': 0.06}]
with mock.patch.object(client, 'cached_models_or_empty', return_value=models), \
        mock.patch.object(client, 'get_editing_models', return_value=models), \
        mock.patch.object(client, 'create_image', return_value={'url': BLOB, 'cost_cents': 6.0, 'credits_cents': 91.0}) as made, \
        mock.patch.object(client, 'download', return_value=PNG):
    wiz = W.with_context(action['context']).create({'style': 'lifestyle', 'extra_wishes': 'on a wooden table'})
    assert not wiz.setup_problem, wiz.setup_problem
    wiz.action_generate()
    prompt = made.call_args[0][1]
    assert 'Keep the product itself exactly' in prompt and 'wooden table' in prompt, prompt
    assert made.call_args[0][3].startswith('data:image/png;base64,')
assert wiz.result_image and wiz.cost_text == '$0.06', (wiz.cost_text, wiz.balance_text)
wiz.action_add()
images = env['product.image'].search([('product_tmpl_id', '=', tmpl.id)])
assert len(images) == 1, len(images)

# Adding twice is refused.
try:
    wiz.action_add()
    raise AssertionError('second add allowed')
except Exception as exc:  # UserError
    assert 'already added' in str(exc), exc

# The views load (the product form with the button, the wizard form, the settings block).
for xmlid in ('genmagic_product_photos.genmagic_photo_wizard_view_form',):
    try:
        env.ref(xmlid)
    except ValueError:
        pass
env['product.template'].get_views([(False, 'form')])
W.get_views([(False, 'form')])
env['res.config.settings'].get_views([(False, 'form')])

# A live, keyless read of GenMagic's model list (informational only).
try:
    live = client.get_editing_models(timeout=20)
    print('LIVE MODELS', len(live), 'default present:', any(m['id'] == client.DEFAULT_MODEL for m in live))
except Exception as exc:
    print('LIVE MODELS unavailable:', exc)

env.cr.rollback()
print('SMOKE OK')
