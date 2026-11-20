import { Dropdown, Label } from "@heroui/react";
import { useNavigate } from "react-router";

import { useThemeControl } from "../../theme/ThemeContext";
import { IconButton } from "../Button";

/** The phone top bar's More: Tools (which has no tab) and the theme. Loaded on phones only. */
export default function MoreMenu() {
  const navigate = useNavigate();
  const theme = useThemeControl();
  return (
    <Dropdown>
      <IconButton kind="quiet" icon="menu" label="More" />
      <Dropdown.Popover placement="bottom end">
        <Dropdown.Menu
          aria-label="More"
          onAction={(key) => {
            if (key === "tools") void navigate("/tools/random-draft");
            if (key === "theme") theme.toggle();
          }}
        >
          <Dropdown.Item id="tools" textValue="Tools">
            <Label>Tools</Label>
          </Dropdown.Item>
          <Dropdown.Item id="theme" textValue="Theme">
            <Label>{theme.isDark ? "Light theme" : "Dark theme"}</Label>
          </Dropdown.Item>
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown>
  );
}
