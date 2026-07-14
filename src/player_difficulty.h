#pragma once
#ifndef CATA_SRC_PLAYER_DIFFICULTY_H
#define CATA_SRC_PLAYER_DIFFICULTY_H

#include <string>
#include <vector>

#include "npc.h"

class Character;
class avatar;

// The point after which stats cost double
constexpr int HIGH_STAT = 12;

// Point pool mode for character creation. Serialized as the integer "limit" in character
// templates, so these values are a stable on-disk contract: FREEFORM=0, ONE_POOL=1,
// MULTI_POOL=2, TRANSFER=3 (TRANSFER must stay 3 so character-transfer templates keep working).
enum class pool_type {
    FREEFORM = 0,
    ONE_POOL = 1,
    MULTI_POOL = 2,
    TRANSFER = 3,
};

// Convert a serialized integer "limit" (from a character template) into a pool_type,
// accepting only the defined values 0-3 and normalizing anything else to FREEFORM.
pool_type pool_type_from_int( int limit );

// True when the given pool constrains the character to a finite point budget and the
// character has overspent it: ONE_POOL when total points used exceed the total pool;
// MULTI_POOL when any of the stat/trait/skill pools is still negative after cross-pool
// borrowing. FREEFORM and TRANSFER are unconstrained and always return false. This is the
// single production predicate consumed by the creator's finalize guard.
bool point_pool_over_allocated( const Character &you, pool_type pool );

// True when the character has not yet spent the entire point pool (used < total).
bool point_pool_has_unspent( const Character &you );

// The point-pool modes the creator offers for a given CHARACTER_POINT_POOLS option value:
// "multi_pool" -> {MULTI_POOL}; "story_teller" -> {FREEFORM}; any other value (i.e. "any")
// -> {FREEFORM, MULTI_POOL, ONE_POOL}. A single-element result means the world fixes the mode.
std::vector<pool_type> pool_selection_modes_for_option( const std::string &option );

class player_difficulty
{
    private:
        player_difficulty();
        ~player_difficulty() = default;

        // calculate individual properties
        std::string get_defense_difficulty( const Character &u ) const;
        std::string get_combat_difficulty( const Character &u ) const;
        std::string get_genetics_difficulty( const Character &u ) const;
        std::string get_expertise_difficulty( const Character &u ) const;
        std::string get_social_difficulty( const Character &u ) const;

        // helpers for the above functions
        static double calc_armor_value( const Character &u );
        static double calc_dps_value( const Character &u );
        static int calc_social_value( const Character &u, const npc &compare );

        // npc helpers
        static void reset_npc( Character &dummy );
        static void npc_from_avatar( const avatar &u, npc &dummy );

        // format the output
        // percent band is the range to consider for values
        // per is the actual percent as a decimal
        // difficulty is true for things going from Very Easy to Very Hard
        // difficutly is false for things going from Very Weak to Very Powerful
        static std::string format_output( float percent_band, float per );

        npc average;

    public:
        const npc &get_average_npc();

        player_difficulty( const player_difficulty & ) = delete;
        player_difficulty &operator= ( const player_difficulty & ) = delete;

        static player_difficulty &getInstance() {
            static player_difficulty instance;
            return instance;
        }

        // call to get the details out
        std::string difficulty_to_string( const avatar &u ) const;
};

#endif // CATA_SRC_PLAYER_DIFFICULTY_H
