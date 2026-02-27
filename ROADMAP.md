# CorridorOne Roadmap: Intelligence Correlation Enhancements

This document outlines the top 5 features a geopolitical intelligence analyst would want, focusing on **correlation between existing data points** and leveraging **free APIs/RSS feeds only**.

---

## Current Correlation Capabilities

### What We Already Do Well

| Signal Type | Description | Data Sources |
|------------|-------------|--------------|
| **Convergence** | 3+ source types report same story within 30min | News feeds |
| **Triangulation** | Wire + Gov + Intel sources align on topic | News feeds |
| **Velocity Spike** | Topic mention rate doubles with 6+ sources/hr | News feeds |
| **Prediction Leading** | Polymarket moves 5%+ with low news coverage | Polymarket + News |
| **Silent Divergence** | Market moves 2%+ with minimal related news | Yahoo/Finnhub + News |
| **Flow/Price Divergence** | Energy price spike without pipeline news | Markets + News |
| **Related Assets** | News stories enriched with nearby infrastructure | Hotspots + All assets |
| **GDELT Tensions** | Country-pair tension scores with 7-day trends | GDELT GPR API |

### What's Missing

1. **No cross-layer correlation** - Protests, military movements, and economic data don't talk to each other
2. **No temporal pattern detection** - Can't detect "unusual for this time of year"
3. **No geographic clustering** - Multiple event types in same region not flagged
4. **No country-level aggregation** - No unified risk view per country
5. **No infrastructure dependency mapping** - Don't show cascade effects

---

## Top 5 Priority Features

### 1. Multi-Signal Geographic Convergence

**What:** When 3+ independent data types converge on the same geographic region within 24-48 hours, generate a high-priority alert.

**Why:** The most valuable I&W (Indications & Warning) signals come from multiple independent sources detecting activity in the same area. A protest + military flight activity + shipping disruption in the same region is far more significant than any single event.

**Data Sources (Already Have):**
- Protests (ACLED/GDELT) → lat/lon
- Military flights (OpenSky) → lat/lon
- Military vessels (AIS) → lat/lon
- Earthquakes/natural events → lat/lon
- News hotspots → lat/lon
- Chokepoint congestion → lat/lon
- Pipeline incidents → lat/lon (inferred)

**Implementation:**
```
1. Define 50km grid cells globally
2. Each refresh cycle, tag events to grid cells
3. Track event counts by type per cell over 24h window
4. Alert when: cell has events from 3+ distinct data types
5. Confidence = function(event_count, type_diversity, time_clustering)
```

**Example Alert:**
> ⚠️ **Geographic Convergence: Taiwan Strait**
> - Military flights: 12 (3x normal)
> - Naval vessels: 8 (2x normal)
> - News velocity: Spike (+340%)
> - Confidence: 87%

---

### 2. Country Instability Index

**What:** Real-time composite risk score for each country, aggregating all available signals into a single 0-100 index.

**Why:** Analysts need a quick way to answer "how stable is Country X right now?" without manually checking 10 different data sources.

**Components (Already Have Data):**
| Component | Source | Weight |
|-----------|--------|--------|
| Protest frequency | ACLED/GDELT | 20% |
| Protest severity | ACLED fatalities | 15% |
| Conflict proximity | Conflict zones | 15% |
| News sentiment | Clustered news | 10% |
| News velocity | RSS feeds | 10% |
| GDELT tension (as target) | GDELT GPR | 10% |
| Sanctions status | Static config | 10% |
| Infrastructure incidents | Cables/pipelines | 10% |

**Free Data to Add:**
- **World Bank Governance Indicators** (annual, free API)
- **UN Refugee Data** (UNHCR, RSS feeds)
- **Election proximity** (static calendar)

**Implementation:**
```
1. Map all events to ISO country codes
2. Maintain rolling 7-day and 30-day baselines per country
3. Calculate Z-scores for each component
4. Weight and sum to 0-100 index
5. Track index changes for trend detection
```

**UI:**
- Choropleth map layer showing index by color
- Sortable country list panel
- Click country → drill-down to component breakdown
- Alert when country moves 10+ points in 24h

---

### 3. Trade Route Risk Scoring

**What:** Real-time risk assessment for major shipping routes, showing which supply chains are most vulnerable right now.

**Why:** Supply chain disruptions are the primary economic consequence of geopolitical events. An analyst needs to quickly assess "if X happens, what trade is affected?"

**Major Routes to Score:**
| Route | Chokepoints | Commodities |
|-------|-------------|-------------|
| Asia → Europe (Suez) | Suez, Bab el-Mandeb, Malacca | Containers, oil |
| Asia → US West Coast | Malacca, Taiwan Strait, Panama | Containers, electronics |
| Middle East → Europe | Hormuz, Suez, Bosphorus | Oil, LNG |
| Russia → Europe | Baltic, Bosphorus | Oil, gas, grain |
| South America → Asia | Panama, Magellan | Commodities, grain |

**Risk Components:**
| Factor | Source | Notes |
|--------|--------|-------|
| Chokepoint congestion | AIS density | Real-time |
| Dark ship activity | AIS gaps | Real-time |
| Weather/storms | NASA EONET | Real-time |
| Conflict proximity | Conflict zones | Static + news |
| Piracy indicators | News keywords | Real-time |
| Sanctions impact | Config | Which ports blocked |
| Port delays | Inferred from AIS | Real-time |

**Implementation:**
```
1. Define route polylines with chokepoint waypoints
2. For each chokepoint, calculate: density_change + gap_rate + weather_alerts + conflict_distance
3. Weight by chokepoint criticality (Hormuz > Malacca > Panama for oil)
4. Sum to 0-100 risk score per route
5. Compare to 30-day baseline for trend
```

**UI:**
- Route lines on map colored by risk (green → yellow → red)
- Panel showing route rankings with trends
- Click route → show chokepoint breakdown
- Alert when route risk jumps 20+ points

---

### 4. Infrastructure Cascade Visualization

**What:** When you click any infrastructure asset, show what depends on it and what would be affected by its disruption.

**Why:** Critical infrastructure is interconnected. A submarine cable fault affects countries downstream. A pipeline disruption affects refineries and ports. Analysts need to see the "so what."

**Dependency Mappings:**

**Ports → dependent on:**
- Pipelines (oil/LNG terminals)
- Submarine cables (data for port operations)
- Nearby naval bases (protection)
- Chokepoints (access routes)

**Cables → serve:**
- Countries (list from cable data)
- Data centers (proximity)
- Financial centers (criticality)

**Pipelines → connect:**
- Origin countries
- Transit countries
- Destination ports/refineries
- Alternate routes

**Implementation:**
```
1. Build static dependency graph in config
2. For cables: map landing points to countries
3. For pipelines: map to origin/transit/destination
4. For ports: map to pipelines that terminate there
5. On asset click: traverse graph, highlight dependents on map
6. Show impact panel: "Disruption would affect: X countries, Y trade volume"
```

**Data Enhancement (Free):**
- **TeleGeography** submarine cable landing points (public)
- **Global Energy Monitor** pipeline database (public)
- **UN COMTRADE** for trade flow volumes (free API)

---

### 5. Temporal Anomaly Detection

**What:** Detect when current activity levels deviate significantly from historical norms for the same time period (day of week, month, season).

**Why:** "Unusual activity" only makes sense in context. Military flights on a Tuesday might be normal; the same level on a Sunday might be significant. Activity in December might be normal for end-of-year exercises but unusual in March.

**What to Track:**
| Data Type | Baseline Period | Anomaly Threshold |
|-----------|-----------------|-------------------|
| Military flights per region | Same weekday, 4-week rolling | Z > 2.0 |
| Naval vessels per chokepoint | Same weekday, 4-week rolling | Z > 2.0 |
| Protest count per country | Same month, 3-year average | Z > 1.5 |
| News velocity per topic | Same weekday, 4-week rolling | Z > 2.5 |
| AIS gaps per region | Same weekday, 4-week rolling | Z > 2.0 |

**Implementation:**
```
1. Store hourly/daily counts by category in IndexedDB
2. Maintain separate baselines by: weekday, month, region
3. On refresh: compare current to same-period baseline
4. Calculate Z-score accounting for seasonal patterns
5. Alert format: "Military flights in Baltic 3.2x normal for Tuesday"
```

**Example Alerts:**
> 📊 **Temporal Anomaly: Baltic Region**
> - Military flights: 47 (normal Tuesday avg: 15)
> - Z-score: 2.8 (highly unusual)
> - Last similar: March 2024 (NATO exercise)

> 📊 **Temporal Anomaly: Iran Protests**
> - Events this week: 23 (normal January avg: 8)
> - Z-score: 1.9 (elevated)
> - Note: Anniversary of 2023 protests approaching

---

## Additional Free Data Sources to Integrate

### Economic/Trade APIs (No Key Required)

| Source | Endpoint | Data | Rate Limit |
|--------|----------|------|------------|
| **World Bank API** | `api.worldbank.org/v2/` | 16,000+ indicators, GDP, trade, FDI | None |
| **IMF Data API** | `dataservices.imf.org/REST/SDMX_JSON.svc/` | IFS, trade flows, balance of payments | None |
| **UN Comtrade** | `comtradeapi.un.org/public/v1/` | Bilateral trade flows by HS code | 100/day free |
| **BIS Statistics** | `stats.bis.org/api/v1/` | Global liquidity, cross-border banking | None |
| **OECD Data** | `stats.oecd.org/SDMX-JSON/` | OECD country indicators | None |

### Food Security (Critical for Instability Correlation)

| Source | Endpoint | Data | Notes |
|--------|----------|------|-------|
| **FAO GIEWS RSS** | `fao.org/giews/english/shortnews/rss.xml` | Food price alerts, country briefs | Add to feeds.ts |
| **FAO Food Price Monitor** | `fpma.fao.org/giews/fpmat4/` | Real-time commodity prices | JSON API |
| **FAO STAT API** | `fenixservices.fao.org/faostat/api/v1/` | Food Price Index, production | REST |

### Sanctions Lists (Critical for Risk Scoring)

| Source | Endpoint | Data | Update Frequency |
|--------|----------|------|------------------|
| **OFAC SDN List** | `sanctionslistservice.ofac.treas.gov/api/` | US sanctions | Daily |
| **EU Sanctions** | `webgate.ec.europa.eu/fsd/fsf/public/files/` | EU restrictive measures | Weekly |
| **UN Sanctions** | `scsanctions.un.org/resources/xml/` | Al-Qaida, DPRK, Iran, etc. | Real-time |
| **OpenSanctions** | `api.opensanctions.org/` | Unified 100+ sources | Free tier: 1000/day |

### Migration/Humanitarian (Instability Indicators)

| Source | Endpoint | Data | Notes |
|--------|----------|------|-------|
| **UNHCR API** | `api.unhcr.org/` | Refugee populations, IDPs, asylum | No key |
| **IOM DTM** | `dtm.iom.int/` | Displacement tracking, migration flows | Free registration |
| **ReliefWeb API** | `api.reliefweb.int/v1/` | Humanitarian reports, disasters | No key |
| **INFORM Risk** | `drmkc.jrc.ec.europa.eu/inform-index/` | Hazard/vulnerability scores | CSV download |

### Think Tank RSS Feeds (Add to feeds.ts)

**Security/Defense:**
- RUSI: `rusi.org/rss.xml`
- Chatham House: `chathamhouse.org/rss.xml`
- ECFR: `ecfr.eu/feed/`
- CFR: `cfr.org/rss`
- Wilson Center: `wilsoncenter.org/rss.xml`
- GMF: `gmfus.org/feed`
- Stimson: `stimson.org/feed/`
- CNAS: `cnas.org/rss`

**Nuclear/Arms Control:**
- Arms Control Association: `armscontrol.org/rss/all`
- FAS: `fas.org/feed/`
- NTI: `nti.org/rss/`
- Bulletin of Atomic Scientists: `thebulletin.org/feed/`

**Regional:**
- Middle East Institute: `mei.edu/rss.xml`
- Lowy Institute (Asia-Pacific): `lowyinstitute.org/feed`
- EU ISS: `iss.europa.eu/rss.xml`

### Static Data (Annual/Quarterly Updates)

| Source | Data | Format | Use Case |
|--------|------|--------|----------|
| **SIPRI Arms Transfers** | Weapons exports by country | CSV | Military capability assessment |
| **SIPRI MILEX** | Military spending | CSV | Defense budget trends |
| **V-Dem** | 400+ democracy indicators | CSV | Governance quality |
| **Fragile States Index** | Country risk scores | CSV | Baseline instability |
| **Freedom House** | Democracy/freedom scores | CSV | Political environment |
| **Global Terrorism Database** | Historical incidents | Registration | Pattern analysis |

### Election Calendar (Static Config)

Maintain election calendar in `src/config/elections.ts`. When election date approaches:
- **30 days**: Add to "upcoming events" panel
- **7 days**: Boost country news correlation
- **1 day**: Increase instability index weighting
- **Election day**: Maximum alert sensitivity

```typescript
interface Election {
  country: string;
  countryCode: string;
  type: 'presidential' | 'parliamentary' | 'referendum' | 'local';
  date: Date;
  significance: 'high' | 'medium' | 'low';
  notes?: string;
}
```

---

## Implementation Priority

| Feature | Complexity | Impact | Priority |
|---------|------------|--------|----------|
| Multi-Signal Geographic Convergence | Medium | Very High | 1 |
| Country Instability Index | Medium | High | 2 |
| Temporal Anomaly Detection | Medium | High | 3 |
| Trade Route Risk Scoring | High | High | 4 |
| Infrastructure Cascade Viz | High | Medium | 5 |

**Recommended approach:** Implement features 1-3 first as they primarily leverage existing data with new correlation logic. Features 4-5 require additional data mapping and UI work.

---

## Technical Notes

### IndexedDB Schema Extensions

```typescript
interface TemporalBaseline {
  type: 'military_flights' | 'vessels' | 'protests' | 'news' | 'ais_gaps';
  region: string;
  weekday: number; // 0-6
  month: number; // 1-12
  hourlyAvg: number[];
  dailyAvg: number;
  stdDev: number;
  sampleCount: number;
  lastUpdated: Date;
}

interface CountryRiskSnapshot {
  countryCode: string;
  timestamp: Date;
  components: {
    protests: number;
    conflict: number;
    sentiment: number;
    velocity: number;
    tension: number;
    sanctions: number;
    infrastructure: number;
  };
  index: number;
  trend: 'rising' | 'stable' | 'falling';
}

interface GeographicCell {
  lat: number;
  lon: number;
  eventTypes: Set<string>;
  eventCount: number;
  firstSeen: Date;
  lastUpdated: Date;
}
```

### New Signal Types

```typescript
type SignalType =
  // Existing
  | 'prediction_leads_news'
  | 'news_leads_markets'
  | 'silent_divergence'
  | 'velocity_spike'
  | 'convergence'
  | 'triangulation'
  | 'flow_drop'
  | 'flow_price_divergence'
  // New
  | 'geographic_convergence'
  | 'country_risk_spike'
  | 'trade_route_risk'
  | 'temporal_anomaly'
  | 'infrastructure_cascade';
```

---

## Conclusion

The most valuable enhancements for a geopolitical analyst focus on **correlation, not accumulation**. The dashboard already aggregates vast amounts of data; the next step is making that data talk to each other.

Priority 1 (Geographic Convergence) alone would significantly elevate the tool's I&W capability by detecting when multiple independent signals point to the same location—the hallmark of significant events.

All proposed features use **existing data sources** or **free APIs/RSS feeds**, keeping with the project's accessible, open-source philosophy.
