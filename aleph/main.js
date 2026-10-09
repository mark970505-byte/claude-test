await document.fonts.load("46px 'Long Cang'", '地下室阿莱夫包含一切的一点');
const F = await import('./film.js');
window.DUR = F.DUR;
window.EV = F.events();
window.TEXTS = F.texts;
window.render = F.render;
window.READY = true;
