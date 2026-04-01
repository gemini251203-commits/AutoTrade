import os
import re

def remove_emojis(text):
    # Base emoji ranges
    emoji_pattern = re.compile(
        u"["
        u"\U0001f600-\U0001f64f"  # emoticons
        u"\U0001f300-\U0001f5ff"  # symbols & pictographs
        u"\U0001f680-\U0001f6ff"  # transport & map symbols
        u"\U0001f1e0-\U0001f1ff"  # flags
        u"\u2600-\u26FF\u2700-\u27BF" # dingbats
        u"\u2300-\u23FF"
        u"]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

changed = []
for root, _, files in os.walk(r'd:\AutoTrade\frontend\src'):
    for f in files:
        if f.endswith(('.vue', '.ts')):
            p = os.path.join(root, f)
            with open(p, 'r', encoding='utf-8') as file:
                content = file.read()
            
            new_content = remove_emojis(content)
            # Hardcoded list of specific emojis often missed by basic ranges or using VS16 (FE0F) variants
            specific_emojis = ['📋', '⚡', '🏆', '💡', '🛡️', '🕒', '🔥', '⚙️', '🤖', '💰', '✨', '📝', '👉', '🔍', '📉', '📈', '⚠️', '⭐', '✔️', '❌']
            for e in specific_emojis:
                new_content = new_content.replace(e, '')
            
            if new_content != content:
                with open(p, 'w', encoding='utf-8') as file:
                    file.write(new_content)
                changed.append(p)

print(f"Updated {len(changed)} files: " + ", ".join([os.path.basename(c) for c in changed]))
