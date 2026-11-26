from odoo import _, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def action_open_genmagic_photos(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("GenMagic photos"),
            'res_model': 'genmagic.photo.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_product_tmpl_id': self.id},
        }
