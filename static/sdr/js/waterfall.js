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

  window.SdrWaterfall = Waterfall;
})();
