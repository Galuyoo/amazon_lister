# Next Steps

## Immediate next step

Refactor the current 3-page Streamlit layout into one main workspace with 3 tabs:

- Product setup
- Listing content
- Review & output

## Implementation rules

- Keep this first refactor layout-only
- Do not change generation logic
- Do not change ready queue behavior
- Do not rename widget keys
- Do not redesign business logic
- Preserve existing session-state behavior as much as possible

## Key architecture rule

The active staged folder and `listing_inputs.json` should define the active listing context when saved inputs exist.

The app should avoid allowing these sources to compete:

- folder name auto-detection
- manual template selector state
- saved listing_inputs.json
- current Streamlit session state

Saved listing context should win when available.

## After tab refactor

Test:

1. Select staged folder
2. Confirm template auto-detection
3. Switch between all tabs
4. Check listing score
5. Mark as Ready
6. Generate from ready queue
7. Restage a finished item
8. Confirm original finished SKU/folder identity is reused

## Later roadmap

- Improve Review & output tab into a serious approval hub
- Add searchable listing archive/history
- Add downloadable historical generated files
- Add worker/admin filtering
- Add AI listing generation and SEO scoring helpers
- Add future template creation workflow
