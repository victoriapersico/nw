# Judge Lab scope and limitations

## Supported UI contract

The Judge Lab intentionally exposes one `Anomaly scope` selection at a time:

| Scope | Optional fields sent in `InjectionConfig` |
|---|---|
| `All traffic` | none |
| `Provider` | `provider` only |
| `Payment method` | `payment_method` only |
| `Issuing bank` | `issuing_bank` only |

Merchant and country are always required. The standalone Judge Lab may also set
a decline code for declines caused by the injection; it does not add another
traffic-slice filter.

The UI renders only the selector for the active scope. Switching scope removes
the previous dimension from the submitted configuration. `Reset demo` calls
`POST /monitor/reset`, clears the local Judge Lab selection, and returns the
scope to `All traffic`.

## Why multiple slice filters are excluded

The backend contracts and evaluation harness can represent intersections such
as provider + issuing bank. They are not part of the reliable live-demo promise.

Detection is performed at merchant + country level. A provider + method,
provider + bank, or method + bank intersection may contain too little traffic to
move the aggregate approval rate enough to satisfy all detector requirements:

- at least 50 merchant-country transactions in the window;
- at least an 8 percentage-point conversion drop;
- a z-score at or below -3;
- persistence across two consecutive windows.

Allowing multiple optional filters in the Judge Lab can therefore create an
active simulator injection without a detected incident. The single-scope UI is
a deliberate reliability constraint, not a limitation of the
`InjectionConfig` schema.

## Supported demo promise

The supported trial-by-fire slices are:

- merchant + country;
- merchant + country + one provider;
- merchant + country + one payment method;
- merchant + country + one issuing bank;
- decline-code degradation when enough declines are present.

Use a strong target approval rate. The known-good path remains Rappi + Brazil +
Stripe at 20% for at least six simulated windows.

## Important distinction

`POST /injections` returning `active` means the simulator accepted the change.
It does not guarantee that the detector will create an incident. Mild changes,
low-volume slices, and unsupported intersections can remain below the detector's
signal policy.
