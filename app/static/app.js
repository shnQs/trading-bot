function app() {
  // Chart instances stored as closure variables — OUTSIDE Alpine's reactive proxy.
  // Alpine wraps everything in the returned object with Proxy for reactivity.
  // TradingView chart objects break when proxied, so they must live here.
  let priceChart = null;
  let candleSeries = null;
  let ema9Series = null;
  let ema21Series = null;
  let rsiChart = null;
  let rsiSeries = null;
  let macdChart = null;
  let macdLineSeries = null;
  let macdSignalSeries = null;
  let macdHistSeries = null;
  let ws = null;

  return {
    // --- Reactive state (safe for Alpine proxy) ---
    wsConnected: false,
    scanning: false,
    lastScanTime: null,
    selectedSymbol: 'BTCUSDT',
    selectedInterval: '1m',
    intervals: ['1m', '5m', '15m', '1h', '4h', '1d'],
    botStatus: {
      running: false,
      testnet: true,
      trading_pairs: ['BTCUSDT', 'ETHUSDT', 'BNBUSDT'],
      risk_per_trade_pct: 1.0,
      max_open_trades: 3,
      stop_loss_pct: 2.0,
      take_profit_pct: 4.0,
    },
    portfolio: {
      total_balance_usdt: 0,
      realized_pnl_today: 0,
      realized_pnl_total: 0,
      win_count: 0,
      loss_count: 0,
      max_drawdown_pct: 0,
      open_trades_count: 0,
    },
    config: { risk_per_trade_pct: 1.0, max_open_trades: 3, stop_loss_pct: 2.0, take_profit_pct: 4.0 },
    openTrades: [],
    closedTrades: [],
    toast: { show: false, message: '', type: 'info' },
    crosshairPrice: null,

    // --- Lifecycle ---
    async init() {
      // Wait for browser to finish layout so offsetWidth/offsetHeight are non-zero
      await new Promise(r => requestAnimationFrame(r));
      await new Promise(r => requestAnimationFrame(r));
      initCharts(this);
      await this.fetchStatus();
      await loadCandles(this.selectedSymbol, this.selectedInterval);
      await this.fetchPortfolio();
      await this.fetchTrades();
      connectWS(this);
      setInterval(async () => {
        await this.fetchPortfolio();
        await this.fetchTrades();
      }, 10000);
    },

    // --- API calls ---
    async fetchStatus() {
      const res = await fetch('/api/bot/status');
      if (!res.ok) return;
      this.botStatus = await res.json();
      this.lastScanTime = this.botStatus.last_scan_time ?? null;
      this.config = {
        risk_per_trade_pct: this.botStatus.risk_per_trade_pct,
        max_open_trades: this.botStatus.max_open_trades,
        stop_loss_pct: this.botStatus.stop_loss_pct,
        take_profit_pct: this.botStatus.take_profit_pct,
      };
      if (this.botStatus.trading_pairs?.length) {
        this.selectedSymbol = this.botStatus.trading_pairs[0];
      }
    },

    async fetchPortfolio() {
      const res = await fetch('/api/portfolio');
      if (!res.ok) return;
      this.portfolio = await res.json();
    },

    async fetchTrades() {
      const [openRes, closedRes] = await Promise.all([
        fetch('/api/trades?status=open&limit=20'),
        fetch('/api/trades?status=closed&limit=50'),
      ]);
      if (openRes.ok) this.openTrades = await openRes.json();
      if (closedRes.ok) this.closedTrades = await closedRes.json();
    },

    async loadCandles() {
      await loadCandles(this.selectedSymbol, this.selectedInterval);
    },

    async changeInterval(iv) {
      this.selectedInterval = iv;
      await loadCandles(this.selectedSymbol, iv);
    },

    async toggleBot() {
      const action = this.botStatus.running ? 'stop' : 'start';
      const res = await fetch(`/api/bot/${action}`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        this.botStatus.running = data.running;
        this.showToast(`Bot ${action}ed`, 'info');
        if (action === 'start') await loadCandles(this.selectedSymbol);
      }
    },

    async saveConfig() {
      const res = await fetch('/api/bot/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.config),
      });
      this.showToast(res.ok ? 'Config saved' : 'Failed to save config', res.ok ? 'info' : 'error');
    },

    async rescan() {
      this.scanning = true;
      try {
        const res = await fetch('/api/bot/scan', { method: 'POST' });
        if (res.ok) {
          const data = await res.json();
          this.botStatus.trading_pairs = data.pairs;
          this.lastScanTime = data.last_scan_time;
          this.selectedSymbol = data.pairs[0] ?? this.selectedSymbol;
          await loadCandles(this.selectedSymbol, this.selectedInterval);
          this.showToast(`Scan complete — ${data.pairs.length} pairs found`, 'info');
        } else {
          this.showToast('Scan failed', 'error');
        }
      } finally {
        this.scanning = false;
      }
    },

    showToast(message, type = 'info') {
      this.toast = { show: true, message, type };
      setTimeout(() => { this.toast.show = false; }, 3000);
    },

    // --- Formatters ---
    fmt(n) { return n != null ? Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 }) : '—'; },
    fmtPnl(n) { return n != null ? (n >= 0 ? '+' : '') + Number(n).toFixed(2) : '—'; },
    winRate() {
      const total = (this.portfolio.win_count ?? 0) + (this.portfolio.loss_count ?? 0);
      return total > 0 ? ((this.portfolio.win_count / total) * 100).toFixed(1) : '0.0';
    },
    timeSince(iso) {
      if (!iso) return '';
      const diff = Date.now() - new Date(iso).getTime();
      const m = Math.floor(diff / 60000);
      return m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ${m % 60}m ago`;
    },
    formatDate(iso) {
      if (!iso) return '';
      return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Vilnius' });
    },
    fmtPrice(n) {
      if (n == null) return '—';
      const p = n >= 1000 ? 2 : n >= 1 ? 4 : n >= 0.1 ? 5 : n >= 0.01 ? 6 : 8;
      return Number(n).toFixed(p);
    },
  };

  // ─── Chart functions (plain JS, no Alpine proxy) ───────────────────────────

  function initCharts(alpine) {
    const chartEl = document.getElementById('priceWrap');
    const rsiEl   = document.getElementById('rsiWrap');
    const macdEl  = document.getElementById('macdWrap');
    console.log('initCharts dimensions — price:', chartEl.offsetWidth, 'x', chartEl.offsetHeight,
                '| rsi:', rsiEl.offsetWidth, 'x', rsiEl.offsetHeight);

    const TZ = 'Europe/Vilnius';
    const tzFmt = (ts, opts) => new Date(ts * 1000).toLocaleString('en-GB', { ...opts, timeZone: TZ });
    const tickMarkFormatter = (time, type) => {
      if (type >= 3) return tzFmt(time, { hour: '2-digit', minute: '2-digit' });
      if (type === 2) return tzFmt(time, { month: 'short', day: 'numeric' });
      if (type === 1) return tzFmt(time, { month: 'short' });
      return tzFmt(time, { year: 'numeric' });
    };
    const baseOpts = {
      layout: { background: { color: '#0d1117' }, textColor: '#8b949e' },
      grid:   { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
      rightPriceScale: { borderColor: '#30363d' },
      timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false, tickMarkFormatter },
      localization: { timeFormatter: ts => tzFmt(ts, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) },
    };

    priceChart = LightweightCharts.createChart(chartEl, {
      ...baseOpts,
      width: chartEl.offsetWidth,
      height: chartEl.offsetHeight,
      crosshair: { mode: 1 },
      timeScale: { ...baseOpts.timeScale, rightOffset: 15 },
    });
    candleSeries  = priceChart.addCandlestickSeries({ upColor: '#3fb950', downColor: '#f85149', borderUpColor: '#3fb950', borderDownColor: '#f85149', wickUpColor: '#3fb950', wickDownColor: '#f85149' });
    ema9Series    = priceChart.addLineSeries({ color: '#58a6ff', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    ema21Series   = priceChart.addLineSeries({ color: '#bc8cff', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });

    rsiChart  = LightweightCharts.createChart(rsiEl, {
      ...baseOpts,
      width: rsiEl.offsetWidth, height: rsiEl.offsetHeight,
      rightPriceScale: { borderColor: '#30363d', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { visible: false }, handleScroll: false, handleScale: false,
    });
    rsiSeries = rsiChart.addLineSeries({ color: '#d29922', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });

    macdChart = LightweightCharts.createChart(macdEl, {
      ...baseOpts,
      width: macdEl.offsetWidth, height: macdEl.offsetHeight,
      rightPriceScale: { borderColor: '#30363d', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { visible: false }, handleScroll: false, handleScale: false,
    });
    macdLineSeries   = macdChart.addLineSeries({ color: '#58a6ff', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    macdSignalSeries = macdChart.addLineSeries({ color: '#f0883e', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    macdHistSeries   = macdChart.addHistogramSeries({ priceFormat: { type: 'price', precision: 6, minMove: 0.000001 } });

    // Crosshair price → statsbar
    priceChart.subscribeCrosshairMove(param => {
      if (param.seriesData && param.seriesData.has(candleSeries)) {
        const bar = param.seriesData.get(candleSeries);
        alpine.crosshairPrice = bar.close ?? bar.value ?? null;
      } else {
        alpine.crosshairPrice = null;
      }
    });

    // Sync scroll
    priceChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
      if (range) rsiChart.timeScale().setVisibleLogicalRange(range);
      if (range) macdChart.timeScale().setVisibleLogicalRange(range);
    });

    // Resize — observe the wrapper divs directly
    new ResizeObserver(() => {
      priceChart.applyOptions({ width: chartEl.offsetWidth, height: chartEl.offsetHeight });
    }).observe(chartEl);
    new ResizeObserver(() => {
      rsiChart.applyOptions({ width: rsiEl.offsetWidth, height: rsiEl.offsetHeight });
    }).observe(rsiEl);
    new ResizeObserver(() => {
      macdChart.applyOptions({ width: macdEl.offsetWidth, height: macdEl.offsetHeight });
    }).observe(macdEl);
  }

  function pricePrecision(price) {
    if (price >= 1000) return { precision: 2, minMove: 0.01 };
    if (price >= 100)  return { precision: 2, minMove: 0.01 };
    if (price >= 10)   return { precision: 3, minMove: 0.001 };
    if (price >= 1)    return { precision: 4, minMove: 0.0001 };
    if (price >= 0.1)  return { precision: 5, minMove: 0.00001 };
    if (price >= 0.01) return { precision: 6, minMove: 0.000001 };
    return               { precision: 8, minMove: 0.00000001 };
  }

  async function loadCandles(symbol, interval = '1m') {
    const res = await fetch(`/api/ohlcv/${symbol}?limit=200&interval=${interval}`);
    if (!res.ok) return;
    const candles = await res.json();
    if (!candles.length) return;

    const times = candles.map(c => Math.floor(c.open_time / 1000));
    const closes = candles.map(c => c.close);
    const lastClose = closes[closes.length - 1];
    const pair = symbol.replace('USDT', '/USDT');
    document.title = `${Number(lastClose).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 8 })} ${pair} | Binance`;

    const fmt = pricePrecision(lastClose);
    candleSeries.applyOptions({ priceFormat: { type: 'price', ...fmt } });
    ema9Series.applyOptions({ priceFormat: { type: 'price', ...fmt } });
    ema21Series.applyOptions({ priceFormat: { type: 'price', ...fmt } });

    candleSeries.setData(candles.map(c => ({
      time: Math.floor(c.open_time / 1000),
      open: c.open, high: c.high, low: c.low, close: c.close,
    })));

    const ema9  = calcEMA(closes, 9);
    const ema21 = calcEMA(closes, 21);
    const rsi   = calcRSI(closes, 14);
    const { macdLine, signalLine, histogram } = calcMACD(closes, 12, 26, 9);

    ema9Series.setData(ema9.map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean));
    ema21Series.setData(ema21.map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean));
    rsiSeries.setData(rsi.map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean));
    macdLineSeries.setData(macdLine.map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean));
    macdSignalSeries.setData(signalLine.map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean));
    macdHistSeries.setData(histogram.map((v, i) => v != null ? {
      time: times[i], value: v, color: v >= 0 ? '#3fb95088' : '#f8514988',
    } : null).filter(Boolean));

    priceChart.timeScale().fitContent();
  }

  function connectWS(alpine) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen  = () => { alpine.wsConnected = true; };
    ws.onclose = () => { alpine.wsConnected = false; setTimeout(() => connectWS(alpine), 3000); };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'candle' && msg.symbol === alpine.selectedSymbol && candleSeries) {
        const c = msg.data;
        candleSeries.update({ time: Math.floor(c.open_time / 1000), open: c.open, high: c.high, low: c.low, close: c.close });
        const fmt = pricePrecision(c.close);
        candleSeries.applyOptions({ priceFormat: { type: 'price', ...fmt } });
        priceChart.timeScale().scrollToRealTime();
        const pair = alpine.selectedSymbol.replace('USDT', '/USDT');
        document.title = `${Number(c.close).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 8 })} ${pair} | Binance`;
      } else if (msg.type === 'portfolio_update') {
        alpine.portfolio = { ...alpine.portfolio, ...msg.data };
      } else if (msg.type === 'trade_update') {
        alpine.fetchTrades();
      }
    };
  }

  // ─── Indicator math ────────────────────────────────────────────────────────

  function calcEMA(closes, period) {
    const result = new Array(closes.length).fill(null);
    const k = 2 / (period + 1);
    let ema = null;
    for (let i = 0; i < closes.length; i++) {
      if (i < period - 1) continue;
      if (ema === null) {
        ema = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
      } else {
        ema = closes[i] * k + ema * (1 - k);
      }
      result[i] = ema;
    }
    return result;
  }

  function calcRSI(closes, period) {
    const result = new Array(closes.length).fill(null);
    if (closes.length < period + 1) return result;
    let gains = 0, losses = 0;
    for (let i = 1; i <= period; i++) {
      const d = closes[i] - closes[i - 1];
      if (d > 0) gains += d; else losses -= d;
    }
    let avgGain = gains / period, avgLoss = losses / period;
    result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    for (let i = period + 1; i < closes.length; i++) {
      const d = closes[i] - closes[i - 1];
      avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
      avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
      result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
    return result;
  }

  function calcMACD(closes, fast, slow, signal) {
    const emaFast = calcEMA(closes, fast);
    const emaSlow = calcEMA(closes, slow);
    const macdLine = closes.map((_, i) =>
      emaFast[i] != null && emaSlow[i] != null ? emaFast[i] - emaSlow[i] : null
    );
    const macdValues = macdLine.filter(v => v != null);
    const sigEMA = calcEMA(macdValues, signal);
    let si = 0;
    const signalLine = macdLine.map(v => v != null ? (sigEMA[si++] ?? null) : null);
    const histogram  = macdLine.map((v, i) =>
      v != null && signalLine[i] != null ? v - signalLine[i] : null
    );
    return { macdLine, signalLine, histogram };
  }
}
