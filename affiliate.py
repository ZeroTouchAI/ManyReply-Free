"""The one place ManyReply's maker can earn something, kept small and visible.

ManyReply is free and open source (MIT). Zernio is the service that posts to Instagram and sends the DMs. If you sign
up for Zernio through the maker's link, the maker earns a commission from Zernio; it does not change your price.

Where the link appears: the README, `python manyreply.py setup` and `doctor` (the places where you are choosing a
Zernio account). It is never put into the posts, captions, DMs, emails or web pages your own install publishes to
your audience. If you fork this, you can swap in your own link or clear it.
"""
ZERNIO_URL = "https://zernio.com"
# The maker's Zernio partner link goes here (partners.dub.co/zernio). Empty means the plain address above is used and
# no affiliate disclosure is shown, because there is nothing to disclose.
ZERNIO_AFFILIATE_URL = ""

DISCLOSURE = ("Affiliate disclosure: this is the maker's referral link. If you sign up through it, the maker of "
              "ManyReply earns a commission from Zernio. It does not change your price.")


def signup_url():
    return ZERNIO_AFFILIATE_URL or ZERNIO_URL


def is_affiliate():
    return bool(ZERNIO_AFFILIATE_URL)


def signup_lines():
    """What to print wherever a person is told to create a Zernio account."""
    lines = [f"Create a Zernio account: {signup_url()}"]
    if is_affiliate():
        lines += [DISCLOSURE, "Open the link in the browser you will sign up with: the referral is remembered by the "
                              "browser, so signing up from another device or after clearing cookies is not counted."]
    return lines
