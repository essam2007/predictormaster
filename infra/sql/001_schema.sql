-- predictormaster database schema (Postgres + TimescaleDB extension).
-- Apply with: psql -f infra/sql/001_schema.sql
-- The dashboard runs without a database (disk cache only); these tables
-- are for the long-running ingestion service.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS sports (
    code        TEXT PRIMARY KEY,
    display     TEXT NOT NULL
);
INSERT INTO sports(code, display) VALUES
  ('nba', 'NBA'), ('nfl', 'NFL'), ('mlb', 'MLB'), ('nhl', 'NHL'),
  ('epl', 'EPL'), ('ncaaf', 'NCAA Football'), ('ncaab', 'NCAA Basketball')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS teams (
    team_id     TEXT PRIMARY KEY,
    sport       TEXT NOT NULL REFERENCES sports(code),
    name        TEXT NOT NULL,
    abbrev      TEXT,
    venue       TEXT,
    UNIQUE (sport, name)
);

CREATE TABLE IF NOT EXISTS games (
    event_id    TEXT PRIMARY KEY,
    sport       TEXT NOT NULL REFERENCES sports(code),
    start_utc   TIMESTAMPTZ NOT NULL,
    home_id     TEXT REFERENCES teams(team_id),
    away_id     TEXT REFERENCES teams(team_id),
    home_name   TEXT NOT NULL,
    away_name   TEXT NOT NULL,
    home_score  DOUBLE PRECISION,
    away_score  DOUBLE PRECISION,
    completed   BOOLEAN NOT NULL DEFAULT false,
    source      TEXT NOT NULL,
    raw         JSONB
);
CREATE INDEX IF NOT EXISTS games_sport_date_idx ON games (sport, start_utc DESC);

-- Per-snapshot odds across venues. Hypertable for fast time-window queries.
CREATE TABLE IF NOT EXISTS odds_snapshots (
    captured_utc    TIMESTAMPTZ NOT NULL,
    event_id        TEXT NOT NULL REFERENCES games(event_id),
    venue           TEXT NOT NULL,        -- 'pinnacle' | 'draftkings' | 'polymarket' | ...
    market          TEXT NOT NULL,        -- 'h2h' | 'spread' | 'total' | 'binary'
    outcome         TEXT NOT NULL,        -- 'home' | 'away' | 'over' | 'under'
    price           DOUBLE PRECISION,     -- decimal odds
    line            DOUBLE PRECISION,     -- spread / total
    implied_prob    DOUBLE PRECISION,
    PRIMARY KEY (captured_utc, event_id, venue, market, outcome)
);
SELECT create_hypertable('odds_snapshots', 'captured_utc', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS odds_event_idx ON odds_snapshots (event_id, captured_utc DESC);

CREATE TABLE IF NOT EXISTS market_prices (
    captured_utc    TIMESTAMPTZ NOT NULL,
    venue           TEXT NOT NULL,        -- 'polymarket' | 'kalshi'
    market_id       TEXT NOT NULL,
    side            TEXT NOT NULL,        -- 'yes' | 'no' | 'home' | 'away'
    mid             DOUBLE PRECISION,
    bid             DOUBLE PRECISION,
    ask             DOUBLE PRECISION,
    last            DOUBLE PRECISION,
    volume          DOUBLE PRECISION,
    event_id        TEXT,
    PRIMARY KEY (captured_utc, venue, market_id, side)
);
SELECT create_hypertable('market_prices', 'captured_utc', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS injuries (
    captured_utc    TIMESTAMPTZ NOT NULL,
    sport           TEXT NOT NULL,
    team            TEXT NOT NULL,
    player          TEXT NOT NULL,
    status          TEXT NOT NULL,
    note            TEXT,
    PRIMARY KEY (captured_utc, sport, team, player)
);
SELECT create_hypertable('injuries', 'captured_utc', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS elo_ratings (
    asof_utc    TIMESTAMPTZ NOT NULL,
    sport       TEXT NOT NULL,
    team        TEXT NOT NULL,
    rating      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (asof_utc, sport, team)
);
SELECT create_hypertable('elo_ratings', 'asof_utc', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS model_predictions (
    produced_utc    TIMESTAMPTZ NOT NULL,
    event_id        TEXT NOT NULL REFERENCES games(event_id),
    model_id        TEXT NOT NULL,
    p_home          DOUBLE PRECISION NOT NULL,
    p_draw          DOUBLE PRECISION,
    p_away          DOUBLE PRECISION NOT NULL,
    expected_margin DOUBLE PRECISION,
    expected_total  DOUBLE PRECISION,
    config_hash     TEXT,
    PRIMARY KEY (produced_utc, event_id, model_id)
);
SELECT create_hypertable('model_predictions', 'produced_utc', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS bet_logs (
    placed_utc    TIMESTAMPTZ NOT NULL,
    event_id      TEXT NOT NULL REFERENCES games(event_id),
    strategy      TEXT NOT NULL,
    side          TEXT NOT NULL,
    odds          DOUBLE PRECISION NOT NULL,
    stake         DOUBLE PRECISION NOT NULL,
    edge          DOUBLE PRECISION,
    closing_odds  DOUBLE PRECISION,
    pnl           DOUBLE PRECISION,
    settled       BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (placed_utc, event_id, strategy, side)
);
CREATE INDEX IF NOT EXISTS bet_logs_strategy_idx ON bet_logs (strategy, placed_utc DESC);

CREATE TABLE IF NOT EXISTS strategy_results (
    asof_utc      TIMESTAMPTZ NOT NULL,
    strategy      TEXT NOT NULL,
    sport         TEXT NOT NULL,
    n_bets        INT NOT NULL,
    win_rate      DOUBLE PRECISION,
    sharpe        DOUBLE PRECISION,
    sortino       DOUBLE PRECISION,
    max_drawdown  DOUBLE PRECISION,
    closing_line_value DOUBLE PRECISION,
    bankroll_end  DOUBLE PRECISION,
    PRIMARY KEY (asof_utc, strategy, sport)
);
SELECT create_hypertable('strategy_results', 'asof_utc', if_not_exists => TRUE);
