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
    selectedSymbol: 'BTCUSDT',
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

    // --- Lifecycle ---
    async init() {
      // Wait for browser to finish layout so offsetWidth/offsetHeight are non-zero
      await new Promise(r => requestAnimationFrame(r));
      await new Promise(r => requestAnimationFrame(r));
      initCharts();
      await this.fetchStatus();
      await loadCandles(this.selectedSymbol);
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
      await loadCandles(this.selectedSymbol);
    },

    async toggleBot() {
      const action = this.botStatus.running ? 'stop' : 'start';
      const res = await fetch(`/api/bot/${action}`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        this.botStatus.running = data.running;
        this.showToast(`Bot ${action}ed`, 'info');
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
      return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    },
  };

  // ─── Chart functions (plain JS, no Alpine proxy) ───────────────────────────

  function initCharts() {
    const chartEl = document.getElementById('priceWrap');
    const rsiEl   = document.getElementById('rsiWrap');
    const macdEl  = document.getElementById('macdWrap');
    console.log('initCharts dimensions — price:', chartEl.offsetWidth, 'x', chartEl.offsetHeight,
                '| rsi:', rsiEl.offsetWidth, 'x', rsiEl.offsetHeight);

    const baseOpts = {
      layout: { background: { color: '#0d1117' }, textColor: '#8b949e' },
      grid:   { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
      rightPriceScale: { borderColor: '#30363d' },
      timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false },
    };

    priceChart = LightweightCharts.createChart(chartEl, {
      ...baseOpts,
      width: chartEl.offsetWidth,
      height: chartEl.offsetHeight,
      crosshair: { mode: 1 },
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

  async function loadCandles(symbol) {
    const res = await fetch(`/api/ohlcv/${symbol}?limit=200`);
    if (!res.ok) return;
    const candles = await res.json();
    if (!candles.length) return;

    const times = candles.map(c => Math.floor(c.open_time / 1000));
    const closes = candles.map(c => c.close);

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
