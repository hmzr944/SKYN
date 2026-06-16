import { FontSource, useFonts as useExpoFonts } from "expo-font"

export function useFonts(fonts: string | Record<string, FontSource>) {
    useExpoFonts(fonts);
    return [true, null]
}
