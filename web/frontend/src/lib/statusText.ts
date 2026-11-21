// Status and execution logs may come from an older server or a third-party tool.
const emoji = /(?:[#*0-9]\uFE0F?\u20E3|\p{Regional_Indicator}{1,2}|(?:\p{Emoji_Presentation}|\p{Extended_Pictographic}\uFE0F)(?:[\uFE0E\uFE0F]|\p{Emoji_Modifier})*(?:\u200D\p{Extended_Pictographic}(?:[\uFE0E\uFE0F]|\p{Emoji_Modifier})*)*)/gu;

export function statusText(value: string): string {
  return value.replace(emoji, '').trim();
}
