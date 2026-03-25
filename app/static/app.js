function app() {
  return {
    // State
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
    config: {
      risk_per_trade_pct: 1.0,
      max_open_trades: 3,
      stop_loss_pct: 2.0,
      take_profit_pct: 4.0,
    },
    openTrades: [],
    closedTrades: [],
    toast: { show: false, message: '', type: 'info' },

    // Chart instances
    _priceChart: null,
    _candleSeries: null,
    _ema9Series: null,
    _ema21Series: null,
    _rsiChart: null,
    _rsiSeries: null,
    _macdChart: null,
    _macdLineSeries: null,
    _macdSignalSeries: null,
    _macdHistSeries: null,
    _ws: null,
    _pollTimer: null,

    async init() {
      this._initCharts();
      await this.fetchStatus();
      await this.loadCandles();
      await this.fetchPortfolio();
      await this.fetchTrades();
      this._connectWS();
      this._startPolling();
    },

    _initCharts() {
      const chartOpts = (container) => ({
        container: document.getElementById(container),
        layout: { background: { color: '#030712' }, textColor: '#9ca3af' },
        grid: { vertLines: { color: '#111827' }, horzLines: { color: '#111827' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#1f2937' },
        timeScale: { borderColor: '#1f2937', timeVisible: true, secondsVisible: false },
        handleScroll: true,
        handleScale: true,
      });

      // Price chart — autoSize fills the container automatically
      this._priceChart = LightweightCharts.createChart(
        document.getElementById('priceChart'),
        { ...chartOpts('priceChart'), autoSize: true }
      );
      this._candleSeries = this._priceChart.addCandlestickSeries({
        upColor: '#22c55e', downColor: '#ef4444',
        borderUpColor: '#22c55e', borderDownColor: '#ef4444',
        wickUpColor: '#22c55e', wickDownColor: '#ef4444',
      });
      this._ema9Series = this._priceChart.addLineSeries({ color: '#60a5fa', lineWidth: 1, title: 'EMA9' });
      this._ema21Series = this._priceChart.addLineSeries({ color: '#fb923c', lineWidth: 1, title: 'EMA21' });

      // RSI chart
      this._rsiChart = LightweightCharts.createChart(
        document.getElementById('rsiChart'),
        { autoSize: true,
          layout: { background: { color: '#030712' }, textColor: '#6b7280' },
          grid: { vertLines: { color: '#111827' }, horzLines: { color: '#111827' } },
          rightPriceScale: { borderColor: '#1f2937', scaleMargins: { top: 0.1, bottom: 0.1 } },
          timeScale: { visible: false }, handleScroll: false, handleScale: false }
      );
      this._rsiSeries = this._rsiChart.addLineSeries({ color: '#a78bfa', lineWidth: 1 });

      // MACD chart
      this._macdChart = LightweightCharts.createChart(
        document.getElementById('macdChart'),
        { autoSize: true,
          layout: { background: { color: '#030712' }, textColor: '#6b7280' },
          grid: { vertLines: { color: '#111827' }, horzLines: { color: '#111827' } },
          rightPriceScale: { borderColor: '#1f2937', scaleMargins: { top: 0.1, bottom: 0.1 } },
          timeScale: { visible: false }, handleScroll: false, handleScale: false }
      );
      this._macdLineSeries = this._macdChart.addLineSeries({ color: '#60a5fa', lineWidth: 1 });
      this._macdSignalSeries = this._macdChart.addLineSeries({ color: '#f59e0b', lineWidth: 1 });
      this._macdHistSeries = this._macdChart.addHistogramSeries({
        color: '#22c55e',
        priceFormat: { type: 'price', precision: 6, minMove: 0.000001 },
      });
    },

    async loadCandles() {
      const res = await fetch(`/api/ohlcv/${this.selectedSymbol}?limit=200`);
      if (!res.ok) return;
      const candles = await res.json();
      if (!candles.length) return;

      const candleData = candles.map(c => ({
        time: Math.floor(c.open_time / 1000),
        open: c.open, high: c.high, low: c.low, close: c.close
      }));
      this._candleSeries.setData(candleData);

      // Calculate indicators client-side for display
      const closes = candles.map(c => c.close);
      const times = candles.map(c => Math.floor(c.open_time / 1000));

      const ema9 = this._calcEMA(closes, 9);
      const ema21 = this._calcEMA(closes, 21);
      const rsi = this._calcRSI(closes, 14);
      const { macdLine, signalLine, histogram } = this._calcMACD(closes, 12, 26, 9);

      this._ema9Series.setData(ema9.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean));
      this._ema21Series.setData(ema21.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean));
      this._rsiSeries.setData(rsi.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean));
      this._macdLineSeries.setData(macdLine.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean));
      this._macdSignalSeries.setData(signalLine.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean));
      this._macdHistSeries.setData(histogram.map((v, i) => v !== null ? {
        time: times[i], value: v, color: v >= 0 ? '#22c55e88' : '#ef444488'
      } : null).filter(Boolean));
    },

    _connectWS() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      this._ws = new WebSocket(`${proto}://${location.host}/ws`);
      this._ws.onopen = () => { this.wsConnected = true; };
      this._ws.onclose = () => {
        this.wsConnected = false;
        setTimeout(() => this._connectWS(), 3000);
      };
      this._ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        this._handleWsMessage(msg);
      };
    },

    _handleWsMessage(msg) {
      if (msg.type === 'candle' && msg.symbol === this.selectedSymbol) {
        const c = msg.data;
        const bar = {
          time: Math.floor(c.open_time / 1000),
          open: c.open, high: c.high, low: c.low, close: c.close
        };
        this._candleSeries.update(bar);
      } else if (msg.type === 'portfolio_update') {
        this.portfolio = { ...this.portfolio, ...msg.data };
      } else if (msg.type === 'trade_update') {
        this.fetchTrades();
      }
    },

    _startPolling() {
      this._pollTimer = setInterval(async () => {
        await this.fetchPortfolio();
        await this.fetchTrades();
      }, 10000);
    },

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
      if (res.ok) {
        this.showToast('Config saved', 'info');
      } else {
        this.showToast('Failed to save config', 'error');
      }
    },

    showToast(message, type = 'info') {
      this.toast = { show: true, message, type };
      setTimeout(() => { this.toast.show = false; }, 3000);
    },

    // --- Indicator calculations ---
    _calcEMA(closes, period) {
      const result = new Array(closes.length).fill(null);
      const k = 2 / (period + 1);
      let ema = null;
      for (let i = 0; i < closes.length; i++) {
        if (i < period - 1) continue;
        if (ema === null) {
          ema = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
          result[i] = ema;
        } else {
          ema = closes[i] * k + ema * (1 - k);
          result[i] = ema;
        }
      }
      return result;
    },

    _calcRSI(closes, period) {
      const result = new Array(closes.length).fill(null);
      if (closes.length < period + 1) return result;
      let gains = 0, losses = 0;
      for (let i = 1; i <= period; i++) {
        const diff = closes[i] - closes[i - 1];
        if (diff > 0) gains += diff; else losses -= diff;
      }
      let avgGain = gains / period;
      let avgLoss = losses / period;
      result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
      for (let i = period + 1; i < closes.length; i++) {
        const diff = closes[i] - closes[i - 1];
        const gain = diff > 0 ? diff : 0;
        const loss = diff < 0 ? -diff : 0;
        avgGain = (avgGain * (period - 1) + gain) / period;
        avgLoss = (avgLoss * (period - 1) + loss) / period;
        result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
      }
      return result;
    },

    _calcMACD(closes, fast, slow, signal) {
      const emaFast = this._calcEMA(closes, fast);
      const emaSlow = this._calcEMA(closes, slow);
      const macdLine = closes.map((_, i) =>
        emaFast[i] !== null && emaSlow[i] !== null ? emaFast[i] - emaSlow[i] : null
      );
      const macdValues = macdLine.filter(v => v !== null);
      const signalEMA = this._calcEMA(macdValues, signal);
      let sigIdx = 0;
      const signalLine = macdLine.map(v => v !== null ? (signalEMA[sigIdx++] ?? null) : null);
      const histogram = macdLine.map((v, i) =>
        v !== null && signalLine[i] !== null ? v - signalLine[i] : null
      );
      return { macdLine, signalLine, histogram };
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
}
