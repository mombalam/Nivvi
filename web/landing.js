const allowedUtm = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"];

function captureUtm() {
  const params = new URLSearchParams(window.location.search);
  const utm = {};
  for (const key of allowedUtm) {
    const val = params.get(key);
    if (val) utm[key] = val;
  }
  return utm;
}

async function track(eventName, properties = {}) {
  const page = document.body?.dataset?.page || "landing";
  try {
    await fetch("/v1/analytics/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_name: eventName,
        page,
        properties,
      }),
    });
  } catch {
    // Silent by design to avoid affecting conversion flow.
  }
}

function setCanonicalAndOgUrl() {
  const origin = window.location.origin;
  const path = window.location.pathname || "/";
  const url = `${origin}${path}`;

  const canonical = document.querySelector('link[rel="canonical"]');
  if (canonical) canonical.setAttribute("href", url);

  const ogUrl = document.querySelector('meta[property="og:url"]');
  if (ogUrl) ogUrl.setAttribute("content", url);
}

function setMessage(form, text, tone = "") {
  const msg = form.querySelector(".form-message");
  if (!msg) return;
  msg.textContent = text;
  msg.classList.remove("success", "error");
  if (tone) msg.classList.add(tone);
}

function validate(form) {
  const fullNameRaw = form.querySelector('input[name="full_name"]')?.value ?? "";
  let firstName = form.querySelector('input[name="first_name"]')?.value?.trim() || "";
  let lastNameRaw = form.querySelector('input[name="last_name"]')?.value ?? "";
  const email = form.querySelector('input[name="email"]')?.value?.trim() || "";
  const phoneNumberRaw = form.querySelector('input[name="phone_number"]')?.value ?? "";
  const consent = Boolean(form.querySelector('input[name="marketing_consent"]')?.checked);
  const normalizedFullName = fullNameRaw.trim().replace(/\s+/g, " ");
  if (!firstName && normalizedFullName) {
    const parts = normalizedFullName.split(" ");
    firstName = parts[0] || "";
    if (!lastNameRaw.trim() && parts.length > 1) {
      lastNameRaw = parts.slice(1).join(" ");
    }
  }
  const lastName = lastNameRaw.trim() || null;
  const phoneNumber = phoneNumberRaw.trim() || null;

  if (!firstName) {
    return { ok: false, error: "Please add your name." };
  }

  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return { ok: false, error: "Please enter a valid email address." };
  }

  if (!consent) {
    return { ok: false, error: "Please confirm consent to receive waitlist updates." };
  }

  if (phoneNumber) {
    if (!/^\+?[0-9().\-\s]{7,32}$/.test(phoneNumber)) {
      return { ok: false, error: "Please enter a valid phone number or leave it blank." };
    }
    const digitsOnly = phoneNumber.replace(/\D/g, "");
    if (digitsOnly.length < 7 || digitsOnly.length > 15) {
      return { ok: false, error: "Please enter a valid phone number or leave it blank." };
    }
  }

  return {
    ok: true,
    first_name: firstName,
    last_name: lastName,
    email,
    phone_number: phoneNumber,
    marketing_consent: consent,
  };
}

function setupReveal() {
  const sections = document.querySelectorAll(".reveal");
  const media = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (media.matches) {
    sections.forEach((el) => el.classList.add("in"));
    return;
  }

  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          io.unobserve(entry.target);
        }
      }
    },
    { threshold: 0.14 }
  );

  sections.forEach((el) => io.observe(el));
}

function setupWaitlist() {
  const utm = captureUtm();
  const forms = document.querySelectorAll(".waitlist-form");

  forms.forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      setMessage(form, "");

      const validation = validate(form);
      if (!validation.ok) {
        setMessage(form, validation.error, "error");
        return;
      }

      const source = form.dataset.source || "landing_hero";
      const successRedirect = (form.dataset.successRedirect || "").trim();
      const button = form.querySelector('button[type="submit"]');
      const defaultLabel =
        (button?.dataset.defaultLabel && button.dataset.defaultLabel.trim()) ||
        button?.textContent?.trim() ||
        "Join the waitlist";
      if (button) button.dataset.defaultLabel = defaultLabel;
      if (button) {
        button.disabled = true;
        button.textContent = "Submitting...";
      }

      try {
        const response = await fetch("/v1/waitlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            first_name: validation.first_name,
            last_name: validation.last_name,
            email: validation.email,
            phone_number: validation.phone_number,
            marketing_consent: validation.marketing_consent,
            source,
            utm,
          }),
        });

        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          const detail = payload?.detail || "We could not save your request right now.";
          throw new Error(typeof detail === "string" ? detail : "Please check your details and try again.");
        }

        const payload = await response.json();
        if (payload.status === "already_exists") {
          await track("waitlist_submit_duplicate", { source });
          if (successRedirect) {
            window.location.assign(`${successRedirect}?status=already_exists`);
            return;
          }
          setMessage(form, "You are already on the list. We will keep you posted.", "success");
        } else {
          await track("waitlist_submit_success", { source });
          if (successRedirect) {
            window.location.assign(`${successRedirect}?status=created`);
            return;
          }
          setMessage(form, "You are in. We will reach out with launch updates.", "success");
          form.reset();
        }
      } catch (error) {
        const message = String(error?.message || "Something went wrong. Please try again.");
        setMessage(form, message, "error");
        await track("waitlist_submit_error", { source });
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = defaultLabel;
        }
      }
    });
  });
}

function setupCtaTracking() {
  const ctas = document.querySelectorAll("[data-analytics-event]");
  for (const cta of ctas) {
    cta.addEventListener("click", () => {
      track(cta.dataset.analyticsEvent, {
        destination: cta.getAttribute("href") || "",
        label: cta.textContent?.trim() || "",
      });
    });
  }
}

function setupFaqTracking() {
  const items = document.querySelectorAll("details[data-faq-id]");
  for (const item of items) {
    item.addEventListener("toggle", () => {
      if (!item.open) return;
      track("faq_expand", { faq_id: item.dataset.faqId || "" });
    });
  }
}

function setupYear() {
  const year = document.querySelector("#year");
  if (year) year.textContent = String(new Date().getFullYear());
}

function setupProtectedAssets() {
  const assets = document.querySelectorAll("[data-protected-asset]");
  for (const asset of assets) {
    asset.addEventListener("contextmenu", (event) => {
      event.preventDefault();
    });

    asset.addEventListener("dragstart", (event) => {
      event.preventDefault();
    });

    asset.addEventListener("selectstart", (event) => {
      event.preventDefault();
    });
  }

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setCanonicalAndOgUrl();
  setupReveal();
  setupWaitlist();
  setupCtaTracking();
  setupFaqTracking();
  setupProtectedAssets();
  setupYear();
  if ((document.body?.dataset?.page || "landing") === "landing") {
    track("landing_view");
  }
});
