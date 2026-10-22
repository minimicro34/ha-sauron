# SAURon Lovelace card — v0.7.0 beta 1 (development)

The card is bundled with SAURon. No Mushroom, ApexCharts or card-mod is required.

## Add the card

After updating and restarting Home Assistant, add a **Manual** card:

```yaml
type: custom:sauron-card
mode: detailed
days: 7
show_chart: true
show_diagnostics: true
```

The integration registers `/sauron/sauron-card.js?v=0.7.0b1` automatically when Lovelace resources use storage mode. For YAML-managed resources, add the URL as a JavaScript module manually.

The card discovers SAURon sensors through the Home Assistant entity registry, by config entry and stable unique ID suffix, not by localized entity names. If multiple SAURon config entries exist, a meter selector appears. Historical data comes from Recorder's external statistics, without writing or modifying Recorder.

## Beta testing

1. Verify the resource appears exactly once in Settings > Dashboards > Resources.
2. Add the card in a test dashboard; retain your existing dashboard.
3. Verify daily/weekly/monthly/yearly values and index against existing native tiles.
4. Check the 7-, 30- and 90-day charts against the native statistics graph.
5. Test compact/detailed modes, visual editor, mobile view and renamed entities.
6. Report browser console and Home Assistant logs if discovery or charts fail.

Do not publish v0.7.0 beta 1 until automated checks and HA runtime verification pass.
