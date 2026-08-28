#!/usr/bin/env bun
import path from "node:path";
import { mkdir, writeFile } from "node:fs/promises";

import {
  buildPrompt,
  detectProvider,
  generateImage,
  getDefaultModel,
  loadEnv,
  normalizeOutputImagePath,
  type CliArgs,
  type Provider,
} from "./baoyu_image_gen_core";

function printUsage(): void {
  console.log(`Usage:
  bun scripts/baoyu_image_gen.ts --prompt "A cat" --image cat.png
  bun scripts/baoyu_image_gen.ts --promptfiles style.md subject.md --image out.png

Options:
  -p, --prompt <text>            Prompt text
  --promptfiles <files...>       Read prompt from files
  --image <path>                 Output image path (required)
  --provider openai|gemini-proxy Force provider
  -m, --model <id>               Model ID
  --ar <ratio>                   Aspect ratio, e.g. 16:9
  --size <WxH>                   Explicit size, e.g. 1024x1024
  --quality normal|2k            Quality preset
  --ref <files...>               Reference image files
  --n <count>                    Number of requested images
  --json                         JSON output
  -h, --help                     Show help

Environment:
  OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_IMAGE_MODEL
  GEMINI_PROXY_API_KEY / GEMINI_PROXY_BASE_URL / GEMINI_PROXY_IMAGE_MODEL`);
}

function parseArgs(argv: string[]): CliArgs {
  const args: CliArgs = {
    prompt: null,
    promptFiles: [],
    imagePath: null,
    provider: null,
    model: null,
    aspectRatio: null,
    size: null,
    quality: "normal",
    referenceImages: [],
    n: 1,
    json: false,
    help: false,
  };

  const takeMany = (index: number): { items: string[]; next: number } => {
    const items: string[] = [];
    let next = index + 1;
    while (next < argv.length && !argv[next]!.startsWith("-")) {
      items.push(argv[next]!);
      next++;
    }
    return { items, next: next - 1 };
  };

  const positionals: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i]!;
    if (token === "-h" || token === "--help") args.help = true;
    else if (token === "--json") args.json = true;
    else if (token === "-p" || token === "--prompt") args.prompt = requireValue(argv[++i], token);
    else if (token === "--image") args.imagePath = requireValue(argv[++i], token);
    else if (token === "--provider") args.provider = requireProvider(requireValue(argv[++i], token));
    else if (token === "-m" || token === "--model") args.model = requireValue(argv[++i], token);
    else if (token === "--ar") args.aspectRatio = requireValue(argv[++i], token);
    else if (token === "--size") args.size = requireValue(argv[++i], token);
    else if (token === "--quality") args.quality = requireQuality(requireValue(argv[++i], token));
    else if (token === "--n") args.n = parseCount(requireValue(argv[++i], token));
    else if (token === "--promptfiles") {
      const { items, next } = takeMany(i);
      if (items.length === 0) throw new Error("Missing files for --promptfiles");
      args.promptFiles.push(...items);
      i = next;
    } else if (token === "--ref" || token === "--reference") {
      const { items, next } = takeMany(i);
      if (items.length === 0) throw new Error(`Missing files for ${token}`);
      args.referenceImages.push(...items);
      i = next;
    } else if (token.startsWith("-")) {
      throw new Error(`Unknown option: ${token}`);
    } else {
      positionals.push(token);
    }
  }

  if (!args.prompt && args.promptFiles.length === 0 && positionals.length > 0) {
    args.prompt = positionals.join(" ");
  }
  return args;
}

function requireValue(value: string | undefined, flag: string): string {
  if (!value) throw new Error(`Missing value for ${flag}`);
  return value;
}

function requireProvider(value: string): Provider {
  if (value === "openai" || value === "gemini-proxy") return value;
  throw new Error(`Invalid provider: ${value}`);
}

function requireQuality(value: string): "normal" | "2k" {
  if (value === "normal" || value === "2k") return value;
  throw new Error(`Invalid quality: ${value}`);
}

function parseCount(value: string): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 1) throw new Error(`Invalid count: ${value}`);
  return parsed;
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printUsage();
    return;
  }

  if (!args.imagePath) {
    printUsage();
    throw new Error("--image is required");
  }

  await loadEnv();
  const prompt = await buildPrompt(args);
  const provider = detectProvider(args);
  const model = args.model || getDefaultModel(provider);
  const outputPath = normalizeOutputImagePath(args.imagePath);

  let image: Uint8Array | null = null;
  let lastError: unknown = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      image = await generateImage(provider, model, prompt, args);
      break;
    } catch (error) {
      lastError = error;
      if (attempt === 0) console.error("Generation failed, retrying...");
    }
  }
  if (!image) throw lastError instanceof Error ? lastError : new Error(String(lastError));

  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, image);

  if (args.json) {
    console.log(
      JSON.stringify(
        {
          savedImage: outputPath,
          provider,
          model,
          promptPreview: prompt.slice(0, 160),
        },
        null,
        2
      )
    );
    return;
  }

  console.log(outputPath);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
