Commons UI fix patch

Copy src/App.jsx and src/OrderGrid.jsx into frontend/src/.
Append the contents of src/order-grid-fix.css to frontend/src/style.css.

Changes:
- Replaces mojibake characters with explicit Unicode escapes in App.jsx.
- Keeps existing API calls and dashboard behavior.
- Reduces Order Intelligence grid to four useful columns: Order ID, Agent / Order, Merchant, Decision.
- Amount and risk remain visible in the selected-order detail panel.
- Uses responsive two-column / one-column layout.

Apply only after backing up the current files, then run npm run build.
