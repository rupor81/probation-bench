# Releasing orders

New orders are released to cutting on the day they arrive, so that cutting never waits for work. The dispatcher sets
the order's status to `released` and puts their name in `released_by`. Cutting works through released orders in due
date order.
