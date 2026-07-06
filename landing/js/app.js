/* ================================================================
   AlphaSwarm Landing — JS Engine
   Lenis + GSAP/ScrollTrigger
   (l'animation 3D du héro — canvas + 150 frames — a été retirée)
   ================================================================ */

const heroSection   = document.querySelector(".hero-standalone");
const siteHeader    = document.querySelector(".site-header");
const scrollContainer = document.getElementById("scroll-container");

/* ================================================================
   5. LENIS SMOOTH SCROLL
   ================================================================ */
gsap.registerPlugin(ScrollTrigger);

const lenis = new Lenis({
  duration: 1.15,
  easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
  smoothWheel: true,
  smoothTouch: false,
});
lenis.on("scroll", ScrollTrigger.update);
gsap.ticker.add((time) => lenis.raf(time * 1000));
gsap.ticker.lagSmoothing(0);

/* ================================================================
   6. HERO INTRO ANIMATION
   ================================================================ */
function playHeroIntro() {
  const tl = gsap.timeline();
  tl.to(".hero-word > span", {
    y: 0,
    opacity: 1,
    duration: 1.1,
    stagger: 0.07,
    ease: "expo.out",
  })
  .to(".hero-tagline", {
    y: 0,
    opacity: 1,
    duration: 1,
    ease: "power3.out",
  }, "-=0.5")
  .from(".hero-corner", {
    y: 16,
    opacity: 0,
    duration: 0.6,
    stagger: 0.1,
    ease: "power2.out",
  }, "-=0.7");
}

/* ================================================================
   7. HEADER SCROLLED STATE
   ================================================================ */
window.addEventListener("scroll", () => {
  if (window.scrollY > window.innerHeight * 0.4) {
    siteHeader.classList.add("scrolled");
  } else {
    siteHeader.classList.remove("scrolled");
  }
});

/* ================================================================
   8. HERO FADE ON SCROLL (ex frame-to-scroll, canvas retiré)
   ================================================================ */
function initHeroFade() {
  ScrollTrigger.create({
    trigger: scrollContainer,
    start: "top top",
    end: "bottom bottom",
    scrub: true,
    onUpdate: (self) => {
      const p = self.progress;

      // Hero fade out as scroll begins
      const heroOpacity = Math.max(0, 1 - p * 14);
      heroSection.style.opacity = heroOpacity;
      heroSection.style.pointerEvents = heroOpacity < 0.05 ? "none" : "auto";
    },
  });
}

/* ================================================================
   9. SECTION ANIMATION SYSTEM
   ================================================================ */
function setupSectionAnimation(section) {
  const type    = section.dataset.animation;
  const persist = section.dataset.persist === "true";
  const enter   = parseFloat(section.dataset.enter) / 100;
  const leave   = parseFloat(section.dataset.leave) / 100;

  const children = section.querySelectorAll(
    ".section-label, .section-heading, .stats-heading, .section-body, " +
    ".section-note, .cta-button, .stat, .agent-list li, .method-list li"
  );
  if (children.length === 0) return;

  const tl = gsap.timeline({ paused: true });

  switch (type) {
    case "fade-up":
      tl.from(children, { y: 50, opacity: 0, stagger: 0.12, duration: 0.9, ease: "power3.out" });
      break;
    case "slide-left":
      tl.from(children, { x: -90, opacity: 0, stagger: 0.13, duration: 0.95, ease: "power3.out" });
      break;
    case "slide-right":
      tl.from(children, { x: 90, opacity: 0, stagger: 0.13, duration: 0.95, ease: "power3.out" });
      break;
    case "scale-up":
      tl.from(children, { scale: 0.85, opacity: 0, stagger: 0.12, duration: 1.0, ease: "power2.out" });
      break;
    case "rotate-in":
      tl.from(children, { y: 40, rotation: 2.5, opacity: 0, stagger: 0.11, duration: 0.95, ease: "power3.out" });
      break;
    case "stagger-up":
      tl.from(children, { y: 70, opacity: 0, stagger: 0.16, duration: 0.95, ease: "power3.out" });
      break;
    case "clip-reveal":
      tl.from(children, { clipPath: "inset(0 0 100% 0)", opacity: 0, stagger: 0.14, duration: 1.1, ease: "power4.inOut" });
      break;
    default:
      tl.from(children, { y: 40, opacity: 0, stagger: 0.12, duration: 0.9, ease: "power3.out" });
  }

  let played = false;
  let leftOnce = false;

  ScrollTrigger.create({
    trigger: scrollContainer,
    start: "top top",
    end: "bottom bottom",
    onUpdate: (self) => {
      const p = self.progress;
      const inRange = p >= enter && p <= leave;
      const past    = p > leave;
      const before  = p < enter;

      if (inRange && !played) {
        section.classList.add("is-active");
        tl.play();
        played = true;
        leftOnce = false;
      } else if (past && played && !persist && !leftOnce) {
        tl.reverse();
        section.classList.remove("is-active");
        leftOnce = true;
        played = false;
      } else if (before && played && !persist) {
        tl.reverse();
        section.classList.remove("is-active");
        played = false;
        leftOnce = false;
      }
    },
  });
}

/* ================================================================
   10. COUNTER ANIMATIONS (stats)
   ================================================================ */
function initCounters() {
  document.querySelectorAll(".stat-number").forEach((el) => {
    const target   = parseFloat(el.dataset.value);
    const decimals = parseInt(el.dataset.decimals || "0", 10);
    const obj = { v: 0 };
    const triggerSection = el.closest(".scroll-section");
    const enter = parseFloat(triggerSection.dataset.enter) / 100;
    const leave = parseFloat(triggerSection.dataset.leave) / 100;
    let played = false;

    ScrollTrigger.create({
      trigger: scrollContainer,
      start: "top top",
      end: "bottom bottom",
      onUpdate: (self) => {
        const p = self.progress;
        if (p >= enter && !played) {
          gsap.to(obj, {
            v: target,
            duration: 2,
            ease: "power1.out",
            onUpdate: () => {
              el.textContent = obj.v.toFixed(decimals);
            },
          });
          played = true;
        } else if (p < enter - 0.02 && played) {
          obj.v = 0;
          el.textContent = (0).toFixed(decimals);
          played = false;
        }
      },
    });
  });
}

/* ================================================================
   11. MARQUEE
   ================================================================ */
function initMarquee() {
  document.querySelectorAll(".marquee-wrap").forEach((el) => {
    const speed = parseFloat(el.dataset.scrollSpeed) || -30;
    const text  = el.querySelector(".marquee-text");
    const start = 0.18, end = 0.86;

    gsap.set(text, { xPercent: 6 });
    gsap.to(text, {
      xPercent: speed,
      ease: "none",
      scrollTrigger: {
        trigger: scrollContainer,
        start: "top top",
        end: "bottom bottom",
        scrub: true,
      },
    });

    ScrollTrigger.create({
      trigger: scrollContainer,
      start: "top top",
      end: "bottom bottom",
      onUpdate: (self) => {
        const p = self.progress;
        let op = 0;
        const fade = 0.05;
        if (p > start - fade && p < start) {
          op = (p - (start - fade)) / fade * 0.5;
        } else if (p >= start && p <= end) {
          op = 0.5;
        } else if (p > end && p < end + fade) {
          op = 0.5 * (1 - (p - end) / fade);
        }
        el.style.opacity = op;
      },
    });
  });
}

/* ================================================================
   12. DARK OVERLAY (for stats section)
   ================================================================ */
function initDarkOverlay() {
  const overlay = document.getElementById("dark-overlay");
  const stats   = document.querySelector(".section-stats");
  if (!stats) return;
  const enter = parseFloat(stats.dataset.enter) / 100;
  const leave = parseFloat(stats.dataset.leave) / 100;
  const fade  = 0.05;

  ScrollTrigger.create({
    trigger: scrollContainer,
    start: "top top",
    end: "bottom bottom",
    scrub: true,
    onUpdate: (self) => {
      const p = self.progress;
      let op = 0;
      if (p >= enter - fade && p < enter) {
        op = (p - (enter - fade)) / fade * 0.9;
      } else if (p >= enter && p <= leave) {
        op = 0.9;
      } else if (p > leave && p <= leave + fade) {
        op = 0.9 * (1 - (p - leave) / fade);
      }
      overlay.style.opacity = op;
    },
  });
}

/* ================================================================
   13. INIT
   ================================================================ */
async function init() {
  // Start hero intro
  playHeroIntro();

  // Wire all scroll-driven systems
  initHeroFade();
  initDarkOverlay();
  initMarquee();
  initCounters();

  document.querySelectorAll(".scroll-section").forEach(setupSectionAnimation);

  // Smooth anchor links via Lenis
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href");
      if (id.length > 1) {
        e.preventDefault();
        const target = document.querySelector(id);
        if (target) lenis.scrollTo(target, { offset: -80 });
      }
    });
  });

  ScrollTrigger.refresh();
}

document.addEventListener("DOMContentLoaded", init);
