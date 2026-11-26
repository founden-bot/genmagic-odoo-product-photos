from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Both values are stored as system parameters. System parameters can only be read through the
    # ORM by administrators; the photo wizard reads them on the server with sudo() and never shows
    # the key to the user who runs it.
    genmagic_consent = fields.Boolean(
        string="Allow sending product photos to GenMagic",
        config_parameter='genmagic_product_photos.consent',
    )
    genmagic_api_key = fields.Char(
        string="GenMagic API key",
        config_parameter='genmagic_product_photos.api_key',
    )
