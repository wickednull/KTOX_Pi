(function(){
  class Waterfall {
    constructor(canvas){
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.width = canvas.width;
      this.height = canvas.height;
      this.clear();
    }

    clear(){
      this.ctx.fillStyle = '#05060a';
      this.ctx.fillRect(0, 0, this.width, this.height);
    }

    color(value){
      const v = Math.max(0, Math.min(255, Number(value) || 0));
      const r = v > 170 ? 255 : Math.floor(v * 1.2);
      const g = v > 90 ? Math.floor((v - 80) * 1.4) : Math.floor(v * 0.35);
      const b = 255 - Math.floor(v * 0.75);
      return `rgb(${r},${Math.max(0, Math.min(255, g))},${Math.max(20, b)})`;
    }

    push(row){
      const image = this.ctx.getImageData(0, 0, this.width, this.height - 1);
      this.ctx.putImageData(image, 0, 1);
      const cellWidth = this.width / row.length;
      row.forEach((value, index) => {
        this.ctx.fillStyle = this.color(value);
        this.ctx.fillRect(index * cellWidth, 0, Math.ceil(cellWidth), 1);
      });
    }
  }

  class Spectrum {
    constructor(canvas){
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.width = canvas.width;
      this.height = canvas.height;
      this.clear();
    }

    clear(){
      this.ctx.fillStyle = '#020617';
      this.ctx.fillRect(0, 0, this.width, this.height);
      this.ctx.strokeStyle = 'rgba(148,163,184,0.18)';
      this.ctx.lineWidth = 1;
      for (let i = 1; i < 4; i += 1) {
        const y = (this.height / 4) * i;
        this.ctx.beginPath();
        this.ctx.moveTo(0, y);
        this.ctx.lineTo(this.width, y);
        this.ctx.stroke();
      }
    }

    draw(row, peaks){
      this.clear();
      const values = Array.isArray(row) ? row : [];
      if (!values.length) return;
      this.ctx.strokeStyle = '#22d3ee';
      this.ctx.lineWidth = 2;
      this.ctx.beginPath();
      values.forEach((value, index) => {
        const x = (index / Math.max(1, values.length - 1)) * this.width;
        const y = this.height - ((Math.max(0, Math.min(255, Number(value) || 0)) / 255) * this.height);
        if (index === 0) this.ctx.moveTo(x, y);
        else this.ctx.lineTo(x, y);
      });
      this.ctx.stroke();
      this.ctx.fillStyle = '#fecaca';
      (peaks || []).forEach((peak) => {
        const x = ((Number(peak.bin) || 0) / Math.max(1, values.length - 1)) * this.width;
        this.ctx.fillRect(x - 1, 0, 2, this.height);
      });
    }
  }

  window.SdrSpectrum = Spectrum;
  window.SdrWaterfall = Waterfall;
})();
