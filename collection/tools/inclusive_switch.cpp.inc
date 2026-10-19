// COLLECTION_INCLUSIVE_EMITTER_V1
// The inclusive ORI/SLTU form uses its bound as scratch after the guard.
static bool collection_inclusive_switch(
    const PS1Executable& exe, uint32_t entry, uint32_t hard_cap,
    uint32_t jr_pc, uint32_t jr_rs, ExactJumpTable& table,
    ExactAddressMapper runtime_to_image, uint32_t producer_lo,
    uint32_t producer_hi) {
    if (entry >= hard_cap || (entry | hard_cap | jr_pc) & 3u ||
        jr_pc < entry || jr_pc - entry < 36u || hard_cap - jr_pc < 8u ||
        jr_pc >= hard_cap || jr_rs == 0u || jr_rs >= 31u) return false;
    const uint32_t start = jr_pc - 36u;
    uint32_t w[11];
    for (uint32_t i = 0; i < 11u; ++i) {
        auto word = exe.read_word(start + 4u * i);
        if (!word.has_value()) return false;
        w[i] = *word;
    }
    const uint32_t limit = (w[0] >> 16u) & 31u;
    const uint32_t index = (w[1] >> 16u) & 31u;
    const uint32_t condition = (w[1] >> 11u) & 31u;
    const uint32_t scaled = (w[3] >> 11u) & 31u;
    const uint32_t base_reg = (w[4] >> 16u) & 31u;
    const uint32_t address = (w[6] >> 11u) & 31u;
    if ((w[0] >> 26u) != 13u || ((w[0] >> 21u) & 31u) != 0u ||
        limit == 0u || (w[0] & 0xffffu) >= 4096u || index == 0u ||
        index == limit || condition == 0u || condition == index ||
        w[1] != (limit << 21u | index << 16u | condition << 11u | 0x2bu) ||
        (w[2] >> 26u) != 5u || ((w[2] >> 21u) & 31u) != condition ||
        ((w[2] >> 16u) & 31u) != 0u || scaled == 0u ||
        w[3] != (index << 16u | scaled << 11u | 2u << 6u) ||
        (w[4] >> 26u) != 15u || ((w[4] >> 21u) & 31u) != 0u ||
        base_reg == 0u || base_reg == scaled || (w[5] >> 26u) != 9u ||
        ((w[5] >> 21u) & 31u) != base_reg ||
        ((w[5] >> 16u) & 31u) != base_reg || address == 0u ||
        (w[6] != (base_reg << 21u | scaled << 16u | address << 11u | 0x21u) &&
         w[6] != (scaled << 21u | base_reg << 16u | address << 11u | 0x21u)) ||
        w[7] != (0x8c000000u | address << 21u | jr_rs << 16u) ||
        w[8] != 0u || w[9] != (jr_rs << 21u | 8u) || w[10] != 0u)
        return false;
    auto control = [&](uint32_t pc) {
        auto word = exe.read_word(pc);
        return !word.has_value() ||
            exact_classify_cf(pc, *word).kind != ExactCfKind::Normal;
    };
    if (start > entry && control(start - 4u)) return false;
    if (producer_lo == 0u && producer_hi == 0u) {
        producer_lo = exe.header.load_address;
        producer_hi = exe.analysis_end_address();
    }
    if (producer_lo >= producer_hi || (producer_lo | producer_hi) & 3u)
        return false;
    const int32_t low = static_cast<int16_t>(w[5] & 0xffffu);
    const uint32_t base = ((w[4] & 0xffffu) << 16u) + low;
    const uint32_t count = (w[0] & 0xffffu) + 1u;
    auto mapped = [&](uint32_t pc) {
        return runtime_to_image ? runtime_to_image(pc, exe) : pc;
    };
    const uint32_t image_base = mapped(base);
    const uint64_t image_end = uint64_t(image_base) + uint64_t(count) * 4u;
    const int64_t default_pc = int64_t(start) + 12 +
        int64_t(static_cast<int16_t>(w[2] & 0xffffu)) * 4;
    if ((base & 3u) != 0u || image_base < producer_lo || image_end > producer_hi ||
        !(image_end <= entry || image_base >= hard_cap) ||
        default_pc < entry || default_pc >= hard_cap ||
        (default_pc >= start && default_pc < int64_t(jr_pc) + 8)) return false;
    ExactJumpTable resolved;
    resolved.table_base = base;
    resolved.table_count = count;
    for (uint32_t i = 0; i < count; ++i) {
        const uint64_t slot = uint64_t(base) + uint64_t(i) * 4u;
        if (slot > 0xffffffffu || mapped(uint32_t(slot)) != image_base + i * 4u)
            return false;
        auto target = exe.read_word(image_base + i * 4u);
        if (!target.has_value() || (*target & 3u) != 0u) return false;
        const uint32_t image_target = mapped(*target);
        if (image_target < jr_pc + 8u || image_target >= hard_cap ||
            image_target < producer_lo || image_target >= producer_hi ||
            (image_target & 3u) != 0u || control(image_target - 4u)) return false;
        auto first = exe.read_word(image_target);
        if (!first.has_value() || !exact_is_valid_mips_word(*first)) return false;
        resolved.targets.emplace_back(*target, image_target);
    }
    // Only a back edge whose delay slot reinstates the exact bound may skip ORI.
    for (uint32_t pc = entry; pc < hard_cap; pc += 4u) {
        auto word = exe.read_word(pc);
        if (!word.has_value()) return false;
        const auto cf = exact_classify_cf(pc, *word);
        const bool direct = cf.kind == ExactCfKind::Branch ||
            cf.kind == ExactCfKind::Jump || cf.kind == ExactCfKind::Jal;
        if (direct && cf.target > start && cf.target <= jr_pc) {
            auto slot = exe.read_word(pc + 4u);
            if (cf.kind == ExactCfKind::Jal || cf.target != start + 4u ||
                !slot.has_value() || *slot != w[0]) return false;
        }
    }
    table = std::move(resolved);
    return true;
}

