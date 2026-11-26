import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models import genmagic_client as client
from ..models import genmagic_styles as styles

PARAM_CONSENT = 'genmagic_product_photos.consent'
PARAM_KEY = 'genmagic_product_photos.api_key'


class GenmagicPhotoWizard(models.TransientModel):
    _name = 'genmagic.photo.wizard'
    _description = "GenMagic product photo"

    product_tmpl_id = fields.Many2one('product.template', string="Product", required=True, readonly=True)
    style = fields.Selection(
        selection=styles.STYLE_LABELS, string="Style", required=True, default=styles.DEFAULT_STYLE,
    )
    extra_wishes = fields.Char(
        string="Extra wishes", size=styles.MAX_EXTRA_LENGTH,
        help="Optional. Up to 300 characters, added to the style.",
    )
    model_name = fields.Selection(
        selection='_selection_models', string="Image model", default=lambda self: self._default_model(),
    )
    setup_problem = fields.Char(compute='_compute_setup_problem')

    result_image = fields.Binary(string="New photo", attachment=False, readonly=True)
    cost_text = fields.Char(readonly=True)
    balance_text = fields.Char(readonly=True)
    use_as_main = fields.Boolean(
        string="Use it as the main product image instead",
        help="Off by default: the photo is added to the product's extra media and the main image stays as it is.",
    )
    added = fields.Boolean(readonly=True)

    # ------------------------------------------------------------------ settings

    @api.model
    def _param(self, key):
        # System parameters are admin-only through the ORM, so the server reads them with sudo().
        return self.env['ir.config_parameter'].sudo().get_param(key) or ''

    @api.model
    def _has_consent(self):
        return self._param(PARAM_CONSENT).lower() in ('true', '1')

    @api.model
    def _api_key(self):
        return self._param(PARAM_KEY).strip()

    @api.model
    def _default_model(self):
        models_ = self._selection_models()
        ids = [m[0] for m in models_]
        return client.DEFAULT_MODEL if client.DEFAULT_MODEL in ids else (ids[0] if ids else False)

    @api.model
    def _selection_models(self):
        # Nothing is fetched before the merchant has agreed to use the service.
        models_ = client.cached_models_or_empty() if self._has_consent() else []
        options = []
        for model in models_:
            label = model['name']
            if model['est_usd'] is not None:
                label = "%s (about $%.2f)" % (label, model['est_usd'])
            options.append((model['id'], label))
        return options or [(client.DEFAULT_MODEL, "Default model")]

    def _problem(self):
        self.ensure_one()
        if not self._has_consent():
            return _(
                "Nothing has been sent yet. To make photos, an administrator must open Settings > GenMagic "
                "and tick the box that allows sending the product's main image to the GenMagic service."
            )
        if not self._api_key():
            return client.no_key_message()
        if not self.product_tmpl_id.with_context(bin_size=True).image_1920:
            return _("This product has no main image. Add one first, then make photos from it.")
        return ''

    @api.depends('product_tmpl_id')
    def _compute_setup_problem(self):
        for wizard in self:
            wizard.setup_problem = wizard._problem() if wizard.product_tmpl_id else ''

    # ------------------------------------------------------------------ actions

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("GenMagic photos"),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_generate(self):
        self.ensure_one()
        problem = self._problem()
        if problem:
            raise UserError(problem)
        product = self.product_tmpl_id
        # Photos cost the merchant money, so only people who may change the product can make them.
        product.check_access('write')

        source = product.image_1920
        source_bytes = base64.b64decode(source) if source else b''
        if len(source_bytes) > client.MAX_SOURCE_BYTES:
            raise UserError(_("The product image is too large to send. Use an image under 2.9 MB."))
        mime = client.detect_mime(source_bytes)
        if not mime:
            raise UserError(_("The product image must be a JPEG, PNG, WebP or GIF."))
        data_url = 'data:%s;base64,%s' % (mime, base64.b64encode(source_bytes).decode('ascii'))

        model = client.pick_model(client.get_editing_models(), self.model_name or '')
        generated = client.create_image(
            self._api_key(), styles.build_prompt(self.style, self.extra_wishes), model['id'], data_url,
        )
        photo = client.download(generated['url'])
        if client.detect_mime(photo) not in ('image/jpeg', 'image/png', 'image/webp'):
            raise UserError(_("GenMagic returned a file that is not a JPEG, PNG or WebP image."))

        self.write({
            'result_image': base64.b64encode(photo),
            'cost_text': self._usd(generated['cost_cents']),
            'balance_text': self._usd(generated['credits_cents']),
            'added': False,
        })
        return self._reopen()

    def action_add(self):
        self.ensure_one()
        if not self.result_image:
            raise UserError(_("Make a photo first."))
        if self.added:
            raise UserError(_("This photo was already added. Make another one to add more."))
        product = self.product_tmpl_id
        product.check_access('write')
        if self.use_as_main:
            product.write({'image_1920': self.result_image})
        else:
            label = dict(self._fields['style'].selection).get(self.style, '')
            self.env['product.image'].create({
                'name': ("%s - GenMagic %s" % (product.name, label))[:200],
                'image_1920': self.result_image,
                'product_tmpl_id': product.id,
            })
        self.added = True
        return self._reopen()

    @staticmethod
    def _usd(cents):
        return '$%.2f' % (cents / 100.0) if cents is not None else ''
