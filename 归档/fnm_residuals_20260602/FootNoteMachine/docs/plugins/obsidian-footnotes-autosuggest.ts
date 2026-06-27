// 来源：https://github.com/MichaBrugger/obsidian-footnotes/blob/master/src/autosuggest.ts
// 插件：obsidian-footnotes（MichaBrugger）— 自动补全建议逻辑

import {
    Editor,
    EditorPosition,
    EditorSuggest,
    EditorSuggestContext,
    EditorSuggestTriggerInfo,
    MarkdownView,
    TFile,
} from "obsidian";
import FootnotePlugin from "./main";
import { AllMarkers, ExtractNameFromFootnote } from "./insert-or-navigate-footnotes"


export class Autocomplete extends EditorSuggest<RegExpMatchArray> {
    plugin: FootnotePlugin;
    latestTriggerInfo: EditorSuggestTriggerInfo;
    cursorPosition: EditorPosition;

    constructor(plugin: FootnotePlugin) {
        super(plugin.app);
        this.plugin = plugin;
    }

    onTrigger(
        cursorPosition: EditorPosition,
        doc: Editor,
        file: TFile
    ): EditorSuggestTriggerInfo | null{
        if (this.plugin.settings.enableAutoSuggest) {

            const mdView = app.workspace.getActiveViewOfType(MarkdownView);
            const lineText = doc.getLine(cursorPosition.line);
            const markdownText = mdView.data;

            let reOnlyMarkersMatches = lineText.match(AllMarkers);

            let markerTarget = null;
            let indexOfMarkerInLine = null;

            if (reOnlyMarkersMatches){
                for (let i = 0; i <= reOnlyMarkersMatches.length; i++) {
                    let marker = reOnlyMarkersMatches[i];
                    if (marker != undefined) {
                        indexOfMarkerInLine = lineText.indexOf(marker);
                        if (
                            cursorPosition.ch >= indexOfMarkerInLine &&
                            cursorPosition.ch <= indexOfMarkerInLine + marker.length
                        ) {
                            markerTarget = marker;
                            break;
                        }
                    }
                }
            }

            if (markerTarget != null) {
                //extract footnote
                let match = markerTarget.match(ExtractNameFromFootnote)
                //find if this footnote exists by listing existing footnote details
                if (match) {
                    let footnoteId = match[2];
                    if (footnoteId !== undefined) {
                        this.latestTriggerInfo = {
                            end: cursorPosition,
                            start: {
                                ch: indexOfMarkerInLine + 2,
                                line: cursorPosition.line
                            },
                            query: footnoteId
                        };
                        return this.latestTriggerInfo
                    }
                }
            }
        return null;
        }
    }

    // 匹配脚注定义名称和完整文本（含多行）
    Footnote_Detail_Names_And_Text = /\[\^([^\[\]]+)\]:(.+(?:\n(?:(?!\[\^[^\[\]]+\]:).)+)*)/g;

    Extract_Footnote_Detail_Names_And_Text(
        doc: Editor
    ) {
        let docText:string = doc.getValue();
        const matches = Array.from(docText.matchAll(this.Footnote_Detail_Names_And_Text));
        return matches;
    }

    getSuggestions = (context: EditorSuggestContext): RegExpMatchArray[] => {
        const { query } = context;

        const mdView = app.workspace.getActiveViewOfType(MarkdownView);
        const doc = mdView.editor;
        const matches = this.Extract_Footnote_Detail_Names_And_Text(doc)
        const filteredResults: RegExpMatchArray[] = matches.filter((entry) => entry[1].includes(query));
        return filteredResults
    };

    renderSuggestion(
        value: RegExpMatchArray,
        el: HTMLElement
    ): void {
        el.createEl("b", { text: value[1] });
        el.createEl("br");
        el.createEl("p", { text: value[2]});
    }

    selectSuggestion(
        value: RegExpMatchArray,
        evt: MouseEvent | KeyboardEvent
    ): void {
        const { context, plugin } = this;
        if (!context) return;

        const mdView = app.workspace.getActiveViewOfType(MarkdownView);
        const doc = mdView.editor;

        const field = value[1];
        const replacement = `${field}`;

        context.editor.replaceRange(
            replacement,
            this.latestTriggerInfo.start,
            this.latestTriggerInfo.end,
        );
    }
}
