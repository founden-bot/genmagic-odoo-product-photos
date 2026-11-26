# GenMagic AI Product Photos for Odoo

Free Odoo app (technical name `genmagic_product_photos`) for Odoo 18.0 and 19.0. A "GenMagic photos" button on the
product form makes a new product photo from the product's main image in one of five styles. The merchant adds the
photos they like to the product's extra media (`product.image`), or, only if they tick it, uses one as the main image.

The photos are paid per photo from the merchant's own prepaid GenMagic balance through their GenMagic API key. There
is no Odoo billing and no activation key.

## Layout

Each folder holds the module that is the root of that version's Git branch for the Odoo Apps store:

```
18.0/genmagic_product_photos   version 18.0.1.0.0
19.0/genmagic_product_photos   version 19.0.1.0.0
```

The two trees are identical except for the manifest version. Keep it that way: change one, copy to the other, then
fix the version line.

## How it works

* Settings > GenMagic holds an opt-in consent checkbox and the API key. Both are system parameters
  (`genmagic_product_photos.consent`, `genmagic_product_photos.api_key`), readable only by administrators. The wizard
  reads them on the server with `sudo()`. Nothing is sent, and the model list is not even fetched, until consent is on.
* `models/genmagic_client.py` is the whole API client (base `https://genmagic.co/api/v1`, Bearer key, `requests` with
  timeouts). It mirrors `integrations/magento-product-photos` and `integrations/wordpress-media`: models from
  `GET /models?category=image` (only models with an image input, same default), `POST /images/generations` with the
  product image as a `data:image` URL, 2.9 MB source limit, download only from GenMagic's media hosts, cost and balance
  from the `x-cost-cents` and `x-credits-remaining` headers, GenMagic's own error text, and a plain "balance too low"
  message on HTTP 402.
* `models/genmagic_styles.py` holds the five styles, their prompts (each with the "keep the product exactly" rule) and
  the 300-character extra wishes.
* `wizard/genmagic_photo_wizard.py` is the transient model behind the button.

Differences from the Magento extension: the image request waits at most 100 seconds (Odoo workers stop requests at
120 s by default), and the result is held in the wizard instead of a temporary file.

## Publishing notes

* Odoo Apps store rules: `apps.odoo.com/apps/vendor-guidelines`. `static/description/index.html` has no external links
  except `mailto:`, no scripts.
* Icon and banner were generated from `apps/app/public/brand/icon.svg`.
* Not run in a real Odoo yet. Before publishing, install on a clean 18.0 and 19.0 database with `website_sale`, set the
  key, make a photo, add it, and check the product's Extra Media.
