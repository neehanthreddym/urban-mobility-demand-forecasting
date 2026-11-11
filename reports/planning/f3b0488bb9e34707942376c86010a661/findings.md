# Final forecast interpretation

The largest zone contribution to absolute error was JFK Airport (ID 132), with MAE 40.94 pickups per zone-hour and WMAPE 15.93%.

The highest average error by clock hour occurred at 23:00 (6.94 pickups per zone-hour).

The highest daily average error occurred on 2025-06-19 (7.96 pickups per zone-hour).

17,622 of 100,608 forecast cells exceeded their zone's initial-training 90th percentile.

Hourly ranks use predicted pickups only. Equal forecasts share the minimum competition rank.

High-demand flags use strict forecast > training percentile and linear percentile interpolation.

34 zones have a zero training 90th percentile. Any positive forecast flags these zones, so review the numeric reference and predicted volume alongside the flag.

The reference is calculated here from the fixed initial training period. Its value was not saved before validation; the percentile rule was specified in the charter before evaluation.

This analysis describes final-test errors. Subsequent model changes require a new future evaluation period.

Available vehicle capacity and unserved requests are unobserved. Planning ranks identify predicted recorded pickup activity. Source timezone and reporting latency remain assumptions.
