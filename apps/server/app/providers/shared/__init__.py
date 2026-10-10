"""Common mechanisms used by server provider adapters and response consumers.

``transport`` owns JSON HTTP retries, deadlines and response-size checks;
``urls`` validates configured base URLs; ``vectors`` validates numeric vectors;
``responses`` validates generated text. These utilities do not define one
provider schema: adapters retain their own payloads and response decoders.
"""
