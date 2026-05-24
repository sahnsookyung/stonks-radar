import type { Locale } from "@frw/shared-types";
import { useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

export function asLocale(value: unknown): Locale {
  return value === "ko" ? "ko" : "en";
}

export function useLocale(): Locale {
  const params = useParams({ strict: false }) as { locale?: string };
  const locale = asLocale(params.locale);
  const { i18n } = useTranslation();
  if (i18n.language !== locale) {
    void i18n.changeLanguage(locale);
  }
  return locale;
}

export function alternateLocale(locale: Locale): Locale {
  return locale === "en" ? "ko" : "en";
}
