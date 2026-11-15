(function(){
  var root=document.documentElement, KEY="site-theme", saved=null;
  try{saved=localStorage.getItem(KEY)}catch(e){}
  if(saved==="dark"||saved==="light"){root.setAttribute("data-theme",saved)}
  document.addEventListener("DOMContentLoaded",function(){
    var btn=document.getElementById("themeBtn"), lbl=document.getElementById("themeLbl");
    function isDark(){var t=root.getAttribute("data-theme");return t?t==="dark":window.matchMedia("(prefers-color-scheme: dark)").matches}
    function sync(){if(lbl)lbl.textContent=isDark()?"Light":"Dark"}
    sync();
    if(btn)btn.addEventListener("click",function(){
      var next=isDark()?"light":"dark"; root.setAttribute("data-theme",next); sync();
      try{localStorage.setItem(KEY,next)}catch(e){}
    });
    var side=document.getElementById("side"), menu=document.getElementById("menuBtn");
    if(menu)menu.addEventListener("click",function(){var o=side.classList.toggle("open");menu.setAttribute("aria-expanded",o?"true":"false")});
  });
})();
