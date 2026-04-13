import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model

st.title("シフト最適化（安定版・完全版）")

# ---------------------------
# 基本設定
# ---------------------------
num_staff = st.number_input("スタッフ人数", 1, 20, 8)
staff_names = [f"スタッフ{i+1}" for i in range(num_staff)]
hours = list(range(24))

# ---------------------------
# 必要人数
# ---------------------------
st.subheader("必要人数")

required = {}
for row in range(0, 24, 6):
    cols = st.columns(6)
    for i in range(6):
        h = row + i
        if h < 24:
            default_val = 1 if 0 <= h <= 6 else 4
            with cols[i]:
                required[h] = st.number_input(
                    f"{h}時", 0, num_staff, default_val, key=f"req_{h}"
                )

# ---------------------------
# 入力
# ---------------------------
work_input = {}
break_input = {}
fixed_input = {}

tabs = st.tabs(staff_names)

for i, s in enumerate(staff_names):
    with tabs[i]:

        st.write(f"### {s}")

        # ナイトボタン
        cbtn1, cbtn2 = st.columns(2)

        if cbtn1.button("🌙 ナイト", key=f"night_{s}"):
            for h in hours:
                st.session_state[f"w_{s}_{h}"] = (h in [22, 23] or 0 <= h <= 6)
                st.session_state[f"b_{s}_{h}"] = not st.session_state[f"w_{s}_{h}"]

        if cbtn2.button("🌙 半ナイト", key=f"half_{s}"):
            for h in hours:
                if h in [21, 22, 23]:
                    st.session_state[f"w_{s}_{h}"] = True
                    st.session_state[f"b_{s}_{h}"] = False
                elif 0 <= h <= 11:
                    st.session_state[f"w_{s}_{h}"] = False
                    st.session_state[f"b_{s}_{h}"] = True

        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown("🟠 勤務")
            for h in hours:
                work_input[(s, h)] = st.checkbox(f"{h}時", key=f"w_{s}_{h}")

        with c2:
            st.markdown("🔵 休憩")
            for h in hours:
                break_input[(s, h)] = st.checkbox(f"{h}時", key=f"b_{s}_{h}")

        with c3:
            st.markdown("📌 固定")
            for h in hours:
                fixed_input[(s, h)] = st.checkbox(f"{h}時", key=f"fix_{s}_{h}")

# ---------------------------
# 解く関数
# ---------------------------
def solve(use_fix):

    model = cp_model.CpModel()
    x = {(s, h): model.NewBoolVar(f"x_{s}_{h}") for s in staff_names for h in hours}

    # 必要人数
    for h in hours:
        model.Add(sum(x[(s, h)] for s in staff_names) == required[h])

    # 休憩希望（絶対）
    for s in staff_names:
        for h in hours:
            if break_input[(s, h)]:
                model.Add(x[(s, h)] == 0)

    # ご飯休憩
    lunch1 = [11, 12, 13]
    lunch2 = [17, 18, 19, 20]

    for s in staff_names:
        model.Add(sum(1 - x[(s, h)] for h in lunch1) >= 1)
        model.Add(sum(1 - x[(s, h)] for h in lunch2) >= 1)

    # 単発休憩禁止
    for s in staff_names:
        for h in [9, 14, 15, 16]:
            if 0 < h < 23:
                model.Add((1 - x[(s, h)]) <= (1 - x[(s, h-1)]) + (1 - x[(s, h+1)]))

    # 早番制約
    for s in staff_names:
        early = model.NewBoolVar(f"early_{s}")
        model.AddMaxEquality(early, [x[(s,6)], x[(s,7)], x[(s,8)]])
        model.Add(x[(s,9)] == 1).OnlyEnforceIf(early)

    # ★ 強化単発勤務禁止
    for s in staff_names:
        for h in range(1, 23):
            model.Add(x[(s, h-1)] + x[(s, h+1)] >= x[(s, h)])

    # ★ 連続勤務6時間まで（5〜22時）
    for s in staff_names:
        for start in range(5, 22 - 6):  # 7時間連続の開始位置
            model.Add(
                sum(x[(s, h)] for h in range(start, start + 7)) <= 6
            )

    # ★ 10時休憩は2時間以上（11時も休憩必須）
    for s in staff_names:
        model.Add((1 - x[(s,10)]) <= (1 - x[(s,11)]))

    # ★ 勤務時間制限（超重要）
    max_hours = 10
    for s in staff_names:
        model.Add(sum(x[(s, h)] for h in hours) <= max_hours)

    # 勤務時間
    total_work = {}
    for s in staff_names:
        total_work[s] = model.NewIntVar(0, 24, f"total_{s}")
        model.Add(total_work[s] == sum(x[(s, h)] for h in hours))

    # 偏り
    avg = sum(required[h] for h in hours) // num_staff
    diff_vars = []

    for s in staff_names:
        diff = model.NewIntVar(0, 24, f"diff_{s}")
        model.AddAbsEquality(diff, total_work[s] - avg)
        diff_vars.append(diff)

    # 最大3ブロック
    for s in staff_names:
        starts = []
        for h in hours:
            if h == 0:
                start = model.NewBoolVar(f"start_{s}_{h}")
                model.Add(start == x[(s, h)])
            else:
                start = model.NewBoolVar(f"start_{s}_{h}")
                model.Add(start >= x[(s, h)] - x[(s, h-1)])
                model.Add(start <= x[(s, h)])
                model.Add(start <= 1 - x[(s, h-1)])
            starts.append(start)
        model.Add(sum(starts) <= 3)

    # 固定
    if use_fix:
        for s in staff_names:
            for h in hours:
                if fixed_input[(s, h)]:
                    model.Add(x[(s, h)] == 1)

    # ★ 安定バランス
    model.Minimize(
        sum(diff_vars) * 50
        - sum(
            20 * x[(s, h)]
            for s in staff_names
            for h in hours
            if work_input[(s, h)]
        )
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10

    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:

        schedule = pd.DataFrame(0, index=staff_names, columns=hours)

        for s in staff_names:
            for h in hours:
                schedule.loc[s, h] = int(solver.Value(x[(s, h)]))

        st.subheader("勤務時間")
        st.dataframe(schedule.sum(axis=1).rename("勤務時間"))

        st.subheader("シフト表")

        display_df = schedule.copy()
        display_df.columns = [f"{h:02d}" for h in hours]

        def color_map(val):
            return "background-color: #F6A068" if val == 1 else "background-color: #FFEEDB"

        styled = display_df.style.map(color_map).format("").set_properties(**{
            "text-align": "center",
            "border": "1px solid #999"
        })

        st.dataframe(styled, use_container_width=True)

    else:
        st.error("❌ 解が見つかりません")

# ---------------------------
# ボタン
# ---------------------------
if st.button("① 自動作成"):
    solve(False)

if st.button("② 固定して再計算"):
    solve(True)
