#include <algorithm>
#include <array>
#include <string>
#include <vector>

#include "avatar.h"
#include "cata_catch.h"
#include "character.h"
#include "character_id.h"
#include "game_constants.h"
#include "mutation.h"
#include "options.h"
#include "player_difficulty.h"
#include "player_helpers.h"
#include "profession.h"
#include "scenario.h"
#include "skill.h"
#include "type_id.h"

namespace
{
// RAII override for the INITIAL_*_POINTS world options. The shared override_option
// helper restores an option by feeding getValue() back into the string setValue();
// these EXTERNAL_OPTION integers are registered with an empty print `format`, so
// getValue() yields "" and the string restore logs a parse error
// (src/options.cpp: "Could not convert '' to an integer"), which the harness treats
// as a test failure. Capturing and restoring the value through the int setValue
// overload avoids that path entirely.
struct scoped_int_option {
    std::string name_;
    int old_value_;
    scoped_int_option( const std::string &name, int value ) :
        name_( name ), old_value_( get_option<int>( name ) ) {
        get_options().get_option( name_ ).setValue( value );
    }
    scoped_int_option( const scoped_int_option & ) = delete;
    scoped_int_option &operator=( const scoped_int_option & ) = delete;
    ~scoped_int_option() {
        get_options().get_option( name_ ).setValue( old_value_ );
    }
};

// ---------------------------------------------------------------------------
// Mirror of the file-local point-math engine in src/newcharacter.cpp (~L249-341).
// The real helpers have internal linkage (`static`) and `struct multi_pool` lives
// in an anonymous namespace, so they cannot be linked from this translation unit
// and there is no src/newcharacter.h to include. These copies reproduce the engine
// formulas verbatim and are driven with REAL avatar data + deterministic option
// overrides.
// ---------------------------------------------------------------------------
int stat_point_pool()
{
    return 4 * 8 + get_option<int>( "INITIAL_STAT_POINTS" );
}
int stat_points_used( const Character &u )
{
    int used = 0;
    for( int stat : {
             u.get_str_base(), u.get_dex_base(), u.get_int_base(), u.get_per_base()
         } ) {
        used += stat + std::max( 0, stat - HIGH_STAT );
    }
    return used;
}
int trait_point_pool()
{
    return get_option<int>( "INITIAL_TRAIT_POINTS" );
}
int trait_points_used( const Character &u )
{
    int used = 0;
    for( const trait_id &cur_trait : u.get_mutations( true ) ) {
        bool locked = get_scenario()->is_locked_trait( cur_trait )
                      || u.prof->is_locked_trait( cur_trait );
        for( const profession *hobby : u.hobbies ) {
            locked = locked || hobby->is_locked_trait( cur_trait );
        }
        if( locked ) {
            continue;
        }
        const mutation_branch &mdata = cur_trait.obj();
        used += mdata.points;
    }
    return used;
}
int skill_point_pool()
{
    return get_option<int>( "INITIAL_SKILL_POINTS" );
}
int skill_points_used( const Character &u )
{
    int scenario = get_scenario()->point_cost();
    int profession_points = u.prof->point_cost();
    int hobbies = 0;
    for( const profession *hobby : u.hobbies ) {
        hobbies += hobby->point_cost();
    }
    int skills = 0;
    for( const Skill &sk : Skill::skills ) {
        static const std::array < int, 1 + MAX_SKILL > costs = { 0, 1, 1, 2, 4, 6, 9, 12, 16, 20, 25 };
        const int skill_level = static_cast<int>( u.get_skill_level( sk.ident() ) );
        skills += costs.at( std::min<int>( skill_level, costs.size() - 1 ) );
    }
    return scenario + profession_points + hobbies + skills;
}
int point_pool_total()
{
    return stat_point_pool() + trait_point_pool() + skill_point_pool();
}
int points_used_total( const Character &u )
{
    return stat_points_used( u ) + trait_points_used( u ) + skill_points_used( u );
}
bool has_unspent_points( const Character &u )
{
    return points_used_total( u ) < point_pool_total();
}

// Mirror of struct multi_pool (anonymous namespace in src/newcharacter.cpp).
// pure_X = pool_X - used_X ; the *_points_left members implement cross-pool
// borrowing: a lower pool's deficit is absorbed by the surplus of higher pools.
struct multi_pool {
    const int pure_stat_points;
    const int pure_trait_points;
    const int pure_skill_points;
    const int stat_points_left;
    const int trait_points_left;
    const int skill_points_left;
    explicit multi_pool( const Character &u ):
        pure_stat_points( stat_point_pool() - stat_points_used( u ) ),
        pure_trait_points( trait_point_pool() - trait_points_used( u ) ),
        pure_skill_points( skill_point_pool() - skill_points_used( u ) ),
        stat_points_left( pure_stat_points
                          + std::min( 0, pure_trait_points
                                      + std::min( 0, pure_skill_points ) ) ),
        trait_points_left( pure_stat_points + pure_trait_points + std::min( 0, pure_skill_points ) ),
        skill_points_left( pure_stat_points + pure_trait_points + pure_skill_points )
    {}
};

// The same three borrowing formulas expressed over explicit pool balances, so the
// cross-pool arithmetic can be checked with exact pairs (including negative balances
// that are awkward to realise on a real avatar).
struct pool_left {
    int stat_left;
    int trait_left;
    int skill_left;
};
pool_left points_left_from_pure( int pure_stat, int pure_trait, int pure_skill )
{
    pool_left r;
    r.stat_left = pure_stat + std::min( 0, pure_trait + std::min( 0, pure_skill ) );
    r.trait_left = pure_stat + pure_trait + std::min( 0, pure_skill );
    r.skill_left = pure_stat + pure_trait + pure_skill;
    return r;
}

// Validity predicates mirroring the finalize guard in
// character_creator_ui::handle_action() (the NEXT_TAB action while the Summary tab
// is selected). ONE_POOL blocks when total used exceeds the total pool; MULTI_POOL
// blocks when any pool is still negative after borrowing; FREEFORM/TRANSFER never
// block on points.
bool one_pool_valid( const Character &u )
{
    return points_used_total( u ) <= point_pool_total();
}
bool multi_pool_valid( const Character &u )
{
    const multi_pool p( u );
    return p.stat_points_left >= 0 && p.trait_points_left >= 0 && p.skill_points_left >= 0;
}
bool finalize_blocked( const Character &u, pool_type pool )
{
    switch( pool ) {
        case pool_type::ONE_POOL:
            return !one_pool_valid( u );
        case pool_type::MULTI_POOL:
            return !multi_pool_valid( u );
        case pool_type::FREEFORM:
        case pool_type::TRANSFER:
        default:
            return false;
    }
}
} // namespace

TEST_CASE( "char_creation_point_pool_enum_values", "[char_creation][points]" )
{
    // pool_type is serialized to character templates as the integer "limit".
    // These values are a backward-compatibility contract and must never change.
    CHECK( static_cast<int>( pool_type::FREEFORM ) == 0 );
    CHECK( static_cast<int>( pool_type::ONE_POOL ) == 1 );
    CHECK( static_cast<int>( pool_type::MULTI_POOL ) == 2 );
    CHECK( static_cast<int>( pool_type::TRANSFER ) == 3 );
}

TEST_CASE( "char_creation_point_pool_arithmetic", "[char_creation][points]" )
{
    avatar &u = get_avatar();
    clear_avatar();
    set_scenario( scenario::generic() ); // clear_avatar() does not set the scenario

    // Deterministic totals irrespective of world-option defaults.
    scoped_int_option opt_stat( "INITIAL_STAT_POINTS", 6 );
    scoped_int_option opt_trait( "INITIAL_TRAIT_POINTS", 0 );
    scoped_int_option opt_skill( "INITIAL_SKILL_POINTS", 2 );

    // The total pool depends only on the options.
    REQUIRE( stat_point_pool() == 4 * 8 + 6 );
    REQUIRE( trait_point_pool() == 0 );
    REQUIRE( skill_point_pool() == 2 );
    CHECK( point_pool_total() == 40 );

    // Freshly cleared survivor: stats all 8, no traits, no skills, generic
    // scenario + profession (both cost 0 points).
    CHECK( stat_points_used( u ) == 32 );
    CHECK( trait_points_used( u ) == 0 );
    CHECK( skill_points_used( u ) == 0 );
    CHECK( points_used_total( u ) == 32 );
    CHECK( has_unspent_points( u ) );
    CHECK( ( points_used_total( u ) < point_pool_total() ) == has_unspent_points( u ) );

    SECTION( "raising a stat costs points, doubling past HIGH_STAT" ) {
        const int before = stat_points_used( u );
        u.set_str_base( 13 );
        const int after = stat_points_used( u );
        CHECK( after - before == 6 );          // (13 + 1) - (8 + 0)
        CHECK( stat_points_used( u ) == 38 );  // 14 + 8 + 8 + 8
    }

    SECTION( "a single stat at 14 costs 16 points" ) {
        u.set_str_base( 14 );
        CHECK( stat_points_used( u ) == 40 );  // 16 + 8 + 8 + 8
    }

    SECTION( "raising a skill spends skill points per the cost table" ) {
        REQUIRE_FALSE( Skill::skills.empty() );
        const skill_id sk = Skill::skills.front().ident();
        const int before = skill_points_used( u );
        u.set_skill_level( sk, 4 );
        CHECK( static_cast<int>( u.get_skill_level( sk ) ) == 4 );
        CHECK( skill_points_used( u ) - before == 4 );
    }

    SECTION( "has_unspent_points is false when the pool is exactly spent" ) {
        scoped_int_option z_stat( "INITIAL_STAT_POINTS", 0 );
        scoped_int_option z_trait( "INITIAL_TRAIT_POINTS", 0 );
        scoped_int_option z_skill( "INITIAL_SKILL_POINTS", 0 );
        REQUIRE( point_pool_total() == 32 );
        REQUIRE( points_used_total( u ) == 32 );
        CHECK_FALSE( has_unspent_points( u ) ); // 32 < 32 is false
    }
}

TEST_CASE( "char_creation_multi_pool_borrowing", "[char_creation][points]" )
{
    // (a) The cross-pool borrowing arithmetic, checked against exact pairs.
    struct borrow_case {
        int pure_stat;
        int pure_trait;
        int pure_skill;
        int stat_left;
        int trait_left;
        int skill_left;
    };
    const std::array<borrow_case, 5> cases = { {
            {   6,  0,  2,    6,   6,   8 },
            { -26,  0,  2,  -26, -26, -24 },
            {  10,  0, -4,    6,   6,   6 },
            {   5, -2,  1,    3,   3,   4 },
            {   3, -1, -5,   -3,  -3,  -3 },
        }
    };
    for( const borrow_case &c : cases ) {
        CAPTURE( c.pure_stat, c.pure_trait, c.pure_skill );
        const pool_left r = points_left_from_pure( c.pure_stat, c.pure_trait, c.pure_skill );
        CHECK( r.stat_left == c.stat_left );
        CHECK( r.trait_left == c.trait_left );
        CHECK( r.skill_left == c.skill_left );
    }

    // (b) multi_pool constructed from a REAL avatar agrees with the formula.
    avatar &u = get_avatar();
    clear_avatar();
    set_scenario( scenario::generic() );
    scoped_int_option opt_stat( "INITIAL_STAT_POINTS", 10 );
    scoped_int_option opt_trait( "INITIAL_TRAIT_POINTS", 0 );
    scoped_int_option opt_skill( "INITIAL_SKILL_POINTS", 0 );

    REQUIRE( multi_pool( u ).pure_stat_points == 10 ); // (4*8+10) - 32
    REQUIRE( multi_pool( u ).pure_trait_points == 0 );
    REQUIRE( multi_pool( u ).pure_skill_points == 0 );

    SECTION( "no deficit: every pool shows the full stat surplus" ) {
        const multi_pool p( u );
        CHECK( p.stat_points_left == 10 );
        CHECK( p.trait_points_left == 10 );
        CHECK( p.skill_points_left == 10 );
    }

    SECTION( "a skill deficit borrows from the stat surplus" ) {
        REQUIRE_FALSE( Skill::skills.empty() );
        const skill_id sk = Skill::skills.front().ident();
        u.set_skill_level( sk, 4 ); // cost 4 -> pure_skill = 0 - 4 = -4
        const multi_pool p( u );
        REQUIRE( p.pure_skill_points == -4 );
        CHECK( p.stat_points_left == 6 );
        CHECK( p.trait_points_left == 6 );
        CHECK( p.skill_points_left == 6 );
        // The avatar-driven struct must agree with the standalone formula.
        const pool_left r = points_left_from_pure( p.pure_stat_points, p.pure_trait_points,
                            p.pure_skill_points );
        CHECK( r.stat_left == p.stat_points_left );
        CHECK( r.trait_left == p.trait_points_left );
        CHECK( r.skill_left == p.skill_points_left );
    }
}

TEST_CASE( "char_creation_point_pool_over_allocation", "[char_creation][points]" )
{
    avatar &u = get_avatar();
    clear_avatar();
    set_scenario( scenario::generic() );
    scoped_int_option opt_stat( "INITIAL_STAT_POINTS", 0 );
    scoped_int_option opt_trait( "INITIAL_TRAIT_POINTS", 0 );
    scoped_int_option opt_skill( "INITIAL_SKILL_POINTS", 0 );
    REQUIRE( point_pool_total() == 32 ); // 4*8 + 0 + 0 + 0

    SECTION( "a balanced survivor is within budget in every pool mode" ) {
        REQUIRE( points_used_total( u ) == 32 );
        CHECK( one_pool_valid( u ) );                              // 32 <= 32
        CHECK( multi_pool_valid( u ) );                            // all pools_left == 0
        CHECK_FALSE( finalize_blocked( u, pool_type::ONE_POOL ) );
        CHECK_FALSE( finalize_blocked( u, pool_type::MULTI_POOL ) );
        CHECK_FALSE( finalize_blocked( u, pool_type::FREEFORM ) );
    }

    SECTION( "over-allocation blocks ONE_POOL and MULTI_POOL but never FREEFORM" ) {
        u.set_str_base( 14 );
        u.set_dex_base( 14 );
        u.set_int_base( 14 );
        u.set_per_base( 14 );
        REQUIRE( points_used_total( u ) == 64 ); // 4 * (14 + 2)

        CHECK_FALSE( one_pool_valid( u ) );   // 64 > 32
        CHECK_FALSE( multi_pool_valid( u ) ); // stat_left = 32 - 64 = -32 < 0

        CHECK( finalize_blocked( u, pool_type::ONE_POOL ) );
        CHECK( finalize_blocked( u, pool_type::MULTI_POOL ) );
        CHECK_FALSE( finalize_blocked( u, pool_type::FREEFORM ) );  // unconstrained
        CHECK_FALSE( finalize_blocked( u, pool_type::TRANSFER ) );  // unconstrained
    }
}

TEST_CASE( "char_creation_template_limit_round_trip", "[char_creation][points]" )
{
    avatar &u = get_avatar();
    const std::string tmpl = "cata_test_point_pool_roundtrip";

    for( const pool_type pool : {
             pool_type::FREEFORM, pool_type::ONE_POOL,
             pool_type::MULTI_POOL, pool_type::TRANSFER
         } ) {
        CAPTURE( static_cast<int>( pool ) );

        clear_avatar();
        set_scenario( scenario::generic() );

        u.save_template( tmpl, pool );

        pool_type loaded = static_cast<pool_type>( 99 ); // sentinel outside the valid set
        // load_template deserializes the saved avatar body, which calls setID(); reset
        // the working avatar's id first so the restore does not log "already a id".
        u.setID( character_id(), true );
        REQUIRE( u.load_template( tmpl, loaded ) );
        CHECK( loaded == pool );
        CHECK( static_cast<int>( loaded ) == static_cast<int>( pool ) );
    }
}

